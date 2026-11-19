#!/usr/bin/env python3
"""danish-tutor's local app: serves app/dist and a small JSON API over the SQLite store.

    python dansk_app.py [--db PATH] [--port N] [--no-browser] [--demo] [--today YYYY-MM-DD]

Database path, first match wins: --db, DANISH_TUTOR_DB, `db_path` in the settings file, then
~/.claude/danish-tutor/dansk.db (the same lookup as dansk_db.py); a missing one is created
empty on the first run. --demo imports the invented
example-data into a fresh temporary database, serves that, and deletes it on exit; its "today"
is 2026-11-06 unless --today is given, so the example dates look current.

Listens on 127.0.0.1 only, port 8765 or the next free one. Every /api request must carry the
per-run token (injected into the served index.html) in the X-Dansk-Token header, and every
request must name 127.0.0.1:<port> or localhost:<port> as its Host, which blocks DNS
rebinding. No CORS headers are sent, so other sites cannot read the API.

API (JSON): GET /api/summary, /api/due, /api/patterns, /api/words?q=&kind=&level=&due=,
/api/words/<id>, /api/items/<id>, /api/sessions, /api/sessions/<id>,
/api/review/preview?item_id=, /api/voice; PUT and DELETE /api/words/<id> and /api/items/<id>;
POST /api/review {item_id, quality, elapsed_seconds}, /api/speak {text, slow}, /api/speak/stop.
Practice sessions (dansk_practice.py): GET /api/practice, POST /api/practice/start {mode,
topic}, GET /api/practice/<sid>/events?after=N (long poll), POST /api/practice/<sid>/message
{text, via}, /end, /retry, /stop.
Writes run in one transaction each; bad input gets 400 with a message and changes nothing.

SM-2 comes from dansk_db.sm2 (Wozniak 1990); nothing here recomputes it. Standard library only.
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dansk_db  # noqa: E402
import dansk_practice  # noqa: E402
import speak  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "app" / "dist"
EXAMPLE = ROOT / "example-data"
DEFAULT_PORT = 8765
DEMO_TODAY = "2026-11-06"
TOKEN_PLACEHOLDER = "__DANSK_TOKEN__"
MAX_BODY = 64 * 1024
MAX_FIELD = 4000
MAX_ELAPSED = 600                 # seconds counted per card at most (a card left open)
QUALITY_LABELS = {1: "Again", 3: "Hard", 4: "Good", 5: "Easy"}


class BadRequest(Exception):
    """Client error: becomes a 400 with this message."""


class NotFound(Exception):
    pass


class Conflict(Exception):
    """The request cannot be done now: becomes a 409 with this message."""


class Unavailable(Exception):
    """No voice: becomes a 503 with this message."""


VOICE_LABELS = {"local": "Local voice", "system": "System voice", "none": "none"}
VOICE_TTL = 60
MAX_SPEAK = 1000
POLL_SECONDS = 20


# ---------------------------------------------------------------- API logic (no HTTP here)

class Api:
    def __init__(self, db: Path, today: str | None = None, demo: bool = False,
                 cfg: dict | None = None):
        self.db = db
        self.fixed_today = today
        self.demo = demo
        self.cfg = dansk_db.load_config() if cfg is None else cfg
        self.lock = threading.Lock()      # one writer at a time
        self.practice = dansk_practice.PracticeManager(db, self.today, self.lock, self.cfg)
        self.voice_cache: tuple[float, str] | None = None
        self.system_cache: tuple[float, bool] | None = None
        self.speech_proc = None
        self.speech_lock = threading.Lock()

    def today(self) -> str:
        return self.fixed_today or date.today().isoformat()

    def con(self):
        return dansk_db.connect(self.db)

    # ---- reads

    def summary(self) -> dict:
        today = self.today()
        d = date.fromisoformat(today)
        first = (d - timedelta(days=13)).isoformat()
        week_start = (d - timedelta(days=d.weekday())).isoformat()
        con = self.con()
        try:
            c = dansk_db.counts(con)
            mins = dansk_db.minutes_by_day(con, first, today)
            revs = dansk_db.reviews_by_day(con, first, today)
            week = dansk_db.minutes_by_day(con, week_start, today)
            days = [(d - timedelta(days=n)).isoformat() for n in range(13, -1, -1)]
            out = {
                "today": today,
                "example_data": dansk_db.get_meta(con, "example_data") == "true",
                "demo": self.demo,
                "learner": dansk_db.get_learner(con),
                "due": dansk_db.count_due(con, today),
                "words": c["words"], "grammar": c["grammar"], "items": c["items"],
                "sessions": c["sessions"], "reviews": c["reviews"],
                "streak": current_streak(dansk_db.session_dates(con), today),
                "minutes_week": sum(week.values()),
                "days": [{"date": x, "minutes": mins.get(x, 0), "reviews": revs.get(x, 0)}
                         for x in days],
                "patterns_due": dansk_db.error_pattern_items(con, today),
                "recent_sessions": dansk_db.session_rows(con)[:5],
            }
        finally:
            con.close()
        return out

    def due(self) -> dict:
        con = self.con()
        try:
            return {"today": self.today(), "cards": dansk_db.due_cards(con, self.today())}
        finally:
            con.close()

    def patterns(self) -> dict:
        con = self.con()
        try:
            return {"today": self.today(), "items": dansk_db.error_pattern_items(con),
                    "frequent": dansk_db.top_error_patterns(con, 20)}
        finally:
            con.close()

    def words(self, query: dict) -> dict:
        q = one(query, "q")[:200]
        kind = one(query, "kind")
        level = one(query, "level")[:20]
        due = one(query, "due")
        if kind not in ("", "word", "grammar"):
            raise BadRequest("kind must be word or grammar")
        if due not in ("", "due", "not_due"):
            raise BadRequest("due must be due or not_due")
        con = self.con()
        try:
            return {"today": self.today(),
                    "words": dansk_db.word_rows(con, self.today(), q, kind, level, due),
                    "levels": dansk_db.word_levels(con)}
        finally:
            con.close()

    def word(self, word_id: int) -> dict:
        con = self.con()
        try:
            w = dansk_db.get_word(con, word_id)
            if w is None:
                raise NotFound()
            w["examples"] = dansk_db.word_examples(con, word_id)
            w["items"] = dansk_db.items_for_word(con, word_id)
            for it in w["items"]:
                it["reviews"] = dansk_db.item_reviews(con, it["id"])
            w["today"] = self.today()
            return w
        finally:
            con.close()

    def sessions(self) -> dict:
        con = self.con()
        try:
            return {"sessions": dansk_db.session_rows(con)}
        finally:
            con.close()

    def session(self, sid: str) -> dict:
        con = self.con()
        try:
            s = dansk_db.get_session(con, sid)
        finally:
            con.close()
        if s is None:
            raise NotFound()
        return s

    def preview(self, query: dict) -> dict:
        item_id = one(query, "item_id")
        con = self.con()
        try:
            it = dansk_db.get_item(con, item_id) if item_id else None
            if it is None:
                raise BadRequest("item_id: no such item")
            opts = dansk_db.preview_review(it, self.today(), QUALITY_LABELS)
        finally:
            con.close()
        for o in opts:
            o["label"] = QUALITY_LABELS[o["quality"]]
        return {"item_id": item_id, "today": self.today(), "options": opts}

    # ---- writes

    def review(self, body) -> dict:
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        unknown = sorted(set(body) - {"item_id", "quality", "elapsed_seconds"})
        if unknown:
            raise BadRequest("unknown key: " + ", ".join(unknown))
        item_id, q = body.get("item_id"), body.get("quality")
        el = body.get("elapsed_seconds", 0)
        if not isinstance(item_id, str) or not item_id:
            raise BadRequest("item_id: required text")
        if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= 5:
            raise BadRequest("quality: must be a whole number 0 to 5")
        if not isinstance(el, (int, float)) or isinstance(el, bool) or el < 0:
            raise BadRequest("elapsed_seconds: must be a number >= 0")
        today = self.today()
        with self.lock:
            con = self.con()
            try:
                if dansk_db.get_item(con, item_id) is None:
                    raise BadRequest("item_id: no such item")
                with con:
                    sid = dansk_db.ensure_app_session(con, today, min(int(el), MAX_ELAPSED))
                    result = dansk_db.apply_review(con, item_id, q, today, sid)
                result["session_id"] = sid
                result["due_left"] = dansk_db.count_due(con, today)
            finally:
                con.close()
        return result

    def edit_word(self, word_id: int, body) -> dict:
        if not isinstance(body, dict) or not body:
            raise BadRequest("body must be a JSON object with at least one field")
        unknown = sorted(set(body) - set(dansk_db.WORD_EDIT_FIELDS))
        if unknown:
            raise BadRequest("not editable: " + ", ".join(unknown))
        fields = clean_fields(body)
        if "headword" in fields and not fields["headword"]:
            raise BadRequest("headword: required text")
        with self.lock:
            con = self.con()
            try:
                if dansk_db.get_word(con, word_id) is None:
                    raise NotFound()
                other = dansk_db.find_word(con, fields["headword"]) if fields.get("headword") else None
                if other is not None and other["id"] != word_id:
                    raise BadRequest("headword: another word already has it")
                with con:
                    dansk_db.update_word(con, word_id, fields)
            finally:
                con.close()
        return self.word(word_id)

    def delete_word(self, word_id: int) -> dict:
        with self.lock:
            con = self.con()
            try:
                if dansk_db.get_word(con, word_id) is None:
                    raise NotFound()
                with con:
                    n = dansk_db.delete_word(con, word_id)
            finally:
                con.close()
        return {"deleted": n}


    # ---- items (what a review card shows)

    def item(self, item_id: str) -> dict:
        con = self.con()
        try:
            it = dansk_db.get_item(con, item_id)
            if it is None:
                raise NotFound()
            d = dict(it)
            d["reviews"] = dansk_db.item_reviews(con, item_id)
            return d
        finally:
            con.close()

    def edit_item(self, item_id: str, body) -> dict:
        if not isinstance(body, dict) or not body:
            raise BadRequest("body must be a JSON object with at least one field")
        unknown = sorted(set(body) - set(dansk_db.ITEM_EDIT_FIELDS))
        if unknown:
            raise BadRequest("not editable: " + ", ".join(unknown))
        fields = clean_fields(body)
        for k in ("content", "answer"):
            if k in fields and not fields[k]:
                raise BadRequest(f"{k}: required text")
        with self.lock:
            con = self.con()
            try:
                if dansk_db.get_item(con, item_id) is None:
                    raise NotFound()
                with con:
                    dansk_db.update_item(con, item_id, fields)
            finally:
                con.close()
        return self.item(item_id)

    def delete_item(self, item_id: str) -> dict:
        with self.lock:
            con = self.con()
            try:
                if dansk_db.get_item(con, item_id) is None:
                    raise NotFound()
                with con:
                    n = dansk_db.delete_item(con, item_id)
            finally:
                con.close()
        return {"deleted": n}

    # ---- voice: speak.py's local daemon first, then the system voice

    def voice_setting(self) -> str:
        v = str(self.cfg.get("voice") or "auto")
        return v if v in speak.VOICES else "auto"

    def system_ok(self) -> bool:
        now = time.monotonic()
        if self.system_cache is None or now - self.system_cache[0] > VOICE_TTL:
            self.system_cache = (now, speak.system_voice_available())
        return self.system_cache[1]

    def voice(self, fresh: bool = False) -> dict:
        now = time.monotonic()
        if fresh or self.voice_cache is None or now - self.voice_cache[0] > VOICE_TTL:
            setting = self.voice_setting()
            if setting in ("auto", "local-daemon") and (speak.daemon_up()
                                                         or speak.daemon_start_command()):
                v = "local"
            elif setting in ("auto", "system") and self.system_ok():
                v = "system"
            else:
                v = "none"
            self.voice_cache = (now, v)
        v = self.voice_cache[1]
        return {"voice": v, "label": VOICE_LABELS[v], "setting": self.voice_setting()}

    def speak(self, body) -> dict:
        """Speak Danish text with the best voice the server has. The text is never logged."""
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        unknown = sorted(set(body) - {"text", "slow"})
        if unknown:
            raise BadRequest("unknown key: " + ", ".join(unknown))
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise BadRequest("text: required")
        if len(text) > MAX_SPEAK:
            raise BadRequest(f"text: at most {MAX_SPEAK} characters")
        slow = bool(body.get("slow"))
        setting = self.voice_setting()
        self.stop_system_speech()
        if setting in ("auto", "local-daemon") and speak.speak_daemon(text):
            self.voice_cache = (time.monotonic(), "local")
            return {"voice": "local"}
        if setting in ("auto", "system") and self.system_ok():
            default = 130 if slow else 150
            try:
                rate = int(self.cfg.get("replay_rate" if slow else "listen_rate") or default)
            except (TypeError, ValueError):
                rate = default
            cmd = speak.system_command(text, max(50, min(400, rate)))
            if not isinstance(cmd, int):
                args, env, stdin = cmd
                proc = subprocess.Popen(args, env=env,
                                        stdin=subprocess.PIPE if stdin is not None else None,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with self.speech_lock:
                    self.speech_proc = proc
                if stdin is not None:
                    threading.Thread(target=feed_stdin, args=(proc, stdin), daemon=True).start()
                self.voice_cache = (time.monotonic(), "system")
                return {"voice": "system"}
        self.voice_cache = (time.monotonic(), "none")
        raise Unavailable("no Danish voice on this computer")

    def stop_system_speech(self):
        with self.speech_lock:
            p, self.speech_proc = self.speech_proc, None
        if p is not None and p.poll() is None:
            p.kill()

    def speak_stop(self) -> dict:
        self.stop_system_speech()
        if self.voice_setting() in ("auto", "local-daemon"):
            speak.stop_daemon()
        return {"stopped": True}

    # ---- practice sessions

    def practice_status(self) -> dict:
        return self.practice.status()

    def practice_start(self, body) -> dict:
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        unknown = sorted(set(body) - {"mode", "topic"})
        if unknown:
            raise BadRequest("unknown key: " + ", ".join(unknown))
        mode = body.get("mode")
        if mode not in dansk_practice.MODES:
            raise BadRequest("mode: must be " + ", ".join(dansk_practice.MODES))
        topic = body.get("topic")
        if topic is not None and not isinstance(topic, str):
            raise BadRequest("topic: must be text")
        topic = (topic or "").strip()[:200] or None
        try:
            s = self.practice.start(mode, topic)
        except dansk_practice.PracticeError as e:
            raise Conflict(str(e))
        return s.snapshot()

    def session_obj(self, sid: str):
        try:
            return self.practice.get(sid)
        except KeyError:
            raise NotFound()

    def practice_events(self, sid: str, query: dict) -> dict:
        s = self.session_obj(sid)
        try:
            after = max(0, int(one(query, "after") or 0))
        except ValueError:
            raise BadRequest("after: must be a whole number")
        evs = s.wait_events(after, POLL_SECONDS)
        return {"events": evs, "session": s.snapshot()}

    def practice_message(self, sid: str, body) -> dict:
        s = self.session_obj(sid)
        if not isinstance(body, dict) or set(body) - {"text", "via"}:
            raise BadRequest("body must be {text, via}")
        text = body.get("text")
        via = body.get("via", "typed")
        if not isinstance(text, str) or not text.strip():
            raise BadRequest("text: required")
        if len(text) > dansk_practice.MAX_MESSAGE:
            raise BadRequest(f"text: at most {dansk_practice.MAX_MESSAGE} characters")
        if via not in ("typed", "voice"):
            raise BadRequest("via: typed or voice")
        return self._act(lambda: s.send(text.strip(), via), s)

    def practice_action(self, sid: str, action: str) -> dict:
        s = self.session_obj(sid)
        fn = {"end": s.end, "retry": s.retry_save, "stop": s.stop}[action]
        return self._act(fn, s)

    @staticmethod
    def _act(fn, s) -> dict:
        try:
            fn()
        except dansk_practice.PracticeError as e:
            raise Conflict(str(e))
        return s.snapshot()


def feed_stdin(proc, text: str):
    try:
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
    except OSError:
        pass


def clean_fields(body: dict) -> dict:
    """Text fields from a JSON body: strings only, at most MAX_FIELD characters, trimmed, and
    an empty string stored as NULL."""
    fields = {}
    for k, v in body.items():
        if v is not None and not isinstance(v, str):
            raise BadRequest(f"{k}: must be text")
        if v is not None and len(v) > MAX_FIELD:
            raise BadRequest(f"{k}: at most {MAX_FIELD} characters")
        v = v.strip() if isinstance(v, str) else v
        fields[k] = v if v else None
    return fields


def one(query: dict, key: str) -> str:
    v = query.get(key) or [""]
    return v[0].strip()


def current_streak(days: list[str], today: str) -> int:
    """Consecutive days with a session, ending today or yesterday; 0 if the latest session is
    older than yesterday."""
    have = set(days)
    d = date.fromisoformat(today)
    if d.isoformat() not in have:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in have:
        n += 1
        d -= timedelta(days=1)
    return n


# ---------------------------------------------------------------- HTTP

ROUTES = [
    ("GET", re.compile(r"^/api/summary$"), lambda a, m, q, b: a.summary()),
    ("GET", re.compile(r"^/api/due$"), lambda a, m, q, b: a.due()),
    ("GET", re.compile(r"^/api/patterns$"), lambda a, m, q, b: a.patterns()),
    ("GET", re.compile(r"^/api/words$"), lambda a, m, q, b: a.words(q)),
    ("GET", re.compile(r"^/api/words/(\d{1,9})$"), lambda a, m, q, b: a.word(int(m[1]))),
    ("PUT", re.compile(r"^/api/words/(\d{1,9})$"), lambda a, m, q, b: a.edit_word(int(m[1]), b)),
    ("DELETE", re.compile(r"^/api/words/(\d{1,9})$"), lambda a, m, q, b: a.delete_word(int(m[1]))),
    ("GET", re.compile(r"^/api/sessions$"), lambda a, m, q, b: a.sessions()),
    ("GET", re.compile(r"^/api/sessions/([A-Za-z0-9_.-]{1,80})$"), lambda a, m, q, b: a.session(m[1])),
    ("GET", re.compile(r"^/api/review/preview$"), lambda a, m, q, b: a.preview(q)),
    ("POST", re.compile(r"^/api/review$"), lambda a, m, q, b: a.review(b)),
    ("GET", re.compile(r"^/api/items/([^/]{1,200})$"), lambda a, m, q, b: a.item(unquote(m[1]))),
    ("PUT", re.compile(r"^/api/items/([^/]{1,200})$"),
     lambda a, m, q, b: a.edit_item(unquote(m[1]), b)),
    ("DELETE", re.compile(r"^/api/items/([^/]{1,200})$"),
     lambda a, m, q, b: a.delete_item(unquote(m[1]))),
    ("GET", re.compile(r"^/api/voice$"), lambda a, m, q, b: a.voice(fresh=one(q, "fresh") == "1")),
    ("POST", re.compile(r"^/api/speak$"), lambda a, m, q, b: a.speak(b)),
    ("POST", re.compile(r"^/api/speak/stop$"), lambda a, m, q, b: a.speak_stop()),
    ("GET", re.compile(r"^/api/practice$"), lambda a, m, q, b: a.practice_status()),
    ("POST", re.compile(r"^/api/practice/start$"), lambda a, m, q, b: a.practice_start(b)),
    ("GET", re.compile(r"^/api/practice/([0-9a-f]{16})/events$"),
     lambda a, m, q, b: a.practice_events(m[1], q)),
    ("POST", re.compile(r"^/api/practice/([0-9a-f]{16})/message$"),
     lambda a, m, q, b: a.practice_message(m[1], b)),
    ("POST", re.compile(r"^/api/practice/([0-9a-f]{16})/(end|retry|stop)$"),
     lambda a, m, q, b: a.practice_action(m[1], m[2])),
]

# Fixed types for what a Vite build emits (the Windows registry can map .js to text/plain).
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8",
         ".map": "application/json; charset=utf-8"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "dansk-app"
    sys_version = ""
    protocol_version = "HTTP/1.0"     # one request per connection: simple and safe here

    # set on the server object: api, dist, token, port
    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code: int, obj):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                  "application/json; charset=utf-8")

    def error(self, code: int, msg: str):
        self.json(code, {"error": msg})

    def host_ok(self) -> bool:
        port = self.server.port
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def handle_any(self):
        try:
            if not self.host_ok():
                return self.error(403, "forbidden host")
            parts = urlsplit(self.path)
            if parts.path.startswith("/api/") or parts.path == "/api":
                return self.api(parts)
            if self.command not in ("GET", "HEAD"):
                return self.error(405, "method not allowed")
            return self.static(parts.path)
        except Exception:                          # never a traceback to the client
            traceback.print_exc(file=sys.stderr)
            try:
                self.error(500, "internal error, see the server console")
            except OSError:
                pass

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = handle_any

    def api(self, parts):
        token = self.headers.get("X-Dansk-Token", "")
        if not hmac.compare_digest(token.encode("utf-8", "replace"), self.server.token.encode()):
            return self.error(403, "missing or wrong token")
        body = None
        if self.command in ("POST", "PUT"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self.error(400, "bad Content-Length")
            if n > MAX_BODY:
                return self.error(400, "body too large")
            raw = self.rfile.read(n) if n > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self.error(400, "body is not valid JSON")
        query = parse_qs(parts.query, keep_blank_values=True)
        allowed = False
        for method, rx, fn in ROUTES:
            m = rx.match(parts.path)
            if not m:
                continue
            allowed = True
            if method != self.command and not (method == "GET" and self.command == "HEAD"):
                continue
            try:
                return self.json(200, fn(self.server.api, m, query, body))
            except BadRequest as e:
                return self.error(400, str(e))
            except NotFound:
                return self.error(404, "not found")
            except Conflict as e:
                return self.error(409, str(e))
            except Unavailable as e:
                return self.error(503, str(e))
            except sqlite3.Error as e:
                traceback.print_exc(file=sys.stderr)
                return self.error(500, f"database error, nothing written: {type(e).__name__}")
        return self.error(405 if allowed else 404, "method not allowed" if allowed else "not found")

    def static(self, url_path: str):
        dist: Path = self.server.dist
        rel = unquote(url_path).lstrip("/") or "index.html"
        if "\x00" in rel or "\\" in rel:
            return self.error(404, "not found")
        target = (dist / rel).resolve()
        if not target.is_relative_to(dist) or not target.is_file():
            return self.error(404, "not found")
        if target == dist / "index.html":
            html = target.read_text(encoding="utf-8").replace(TOKEN_PLACEHOLDER, self.server.token)
            return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                             {"Content-Security-Policy": CSP})
        ctype = (TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
                 or "application/octet-stream")
        return self.send(200, target.read_bytes(), ctype)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port; turn it off there so a taken
    # port is detected and the next one is tried.
    allow_reuse_address = os.name != "nt"


def make_server(db: Path, dist: Path = DIST, port: int = DEFAULT_PORT, today: str | None = None,
                demo: bool = False, tries: int = 20, quiet: bool = False,
                cfg: dict | None = None) -> AppServer:
    """Bind on 127.0.0.1, trying `port` and the next ones (port 0: any free port)."""
    last = None
    for p in ([0] if port == 0 else range(port, port + tries)):
        try:
            srv = AppServer(("127.0.0.1", p), Handler)
            break
        except OSError as e:
            last = e
    else:
        raise OSError(f"no free port from {port} to {port + tries - 1}: {last}")
    srv.port = srv.server_address[1]
    srv.api = Api(db, today, demo, cfg)
    srv.dist = dist.resolve()
    srv.token = secrets.token_urlsafe(32)
    srv.quiet = quiet
    return srv


def create_db(path: Path) -> None:
    """A new, empty database with the learner row from the settings (first run)."""
    cfg = dansk_db.load_config()
    con = dansk_db.connect(path)
    try:
        with con:
            dansk_db.set_learner(con, level=cfg.get("level") or "A2",
                                 target_level=cfg.get("target_level") or "B2",
                                 support_language=cfg.get("support_language") or "English")
    finally:
        con.close()


def build_demo_db(folder: Path) -> Path:
    import import_fluent
    path = folder / "demo.db"
    con = dansk_db.connect(path)
    try:
        with con:
            import_fluent.import_all(con, EXAMPLE, EXAMPLE / "words")
            dansk_db.set_meta(con, "example_data", "true")
            if not dansk_db.get_learner(con):
                dansk_db.set_learner(con, level="A2", target_level="B2", support_language="English")
    finally:
        con.close()
    return path


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # URL visible when piped
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="danish-tutor local app (127.0.0.1 only)")
    ap.add_argument("--db", help="database file (overrides DANISH_TUTOR_DB and db_path)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="first port to try (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    ap.add_argument("--demo", action="store_true",
                    help="serve the invented example data from a temporary database")
    ap.add_argument("--today", help="treat this YYYY-MM-DD as today (default: the real date; "
                                    f"{DEMO_TODAY} with --demo)")
    a = ap.parse_args(argv)

    if a.today and not dansk_db.is_date(a.today):
        print("--today must be YYYY-MM-DD")
        return 1
    if not (DIST / "index.html").is_file():
        print(f"the app is not built: {DIST / 'index.html'} is missing.")
        print("Build it once with: cd app && npm ci && npm run build")
        return 1

    tmp = None
    if a.demo:
        if a.db:
            print("pass either --db or --demo, not both")
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="dansk-demo-"))
        db = build_demo_db(tmp)
        today = a.today or DEMO_TODAY
    else:
        db = dansk_db.db_path(a.db)
        today = a.today
        if not db.is_file():
            try:
                create_db(db)
            except (sqlite3.Error, OSError) as e:
                print(f"cannot create a database at {db}: {e}")
                return 1
            print(f"created a new, empty database at {db}")
        try:
            dansk_db.connect(db).close()    # upgrade an older schema once, before parallel requests
        except sqlite3.Error as e:
            print(f"cannot open the database at {db}: {e}")
            return 1
    try:
        try:
            srv = make_server(db, DIST, a.port, today, a.demo)
        except OSError as e:
            print(f"cannot start: {e}")
            return 1
        url = f"http://127.0.0.1:{srv.port}/"
        print(f"danish-tutor app: {url}")
        print(f"  database: {'demo (temporary copy of example-data)' if a.demo else db}")
        print("  Ctrl+C stops it")
        if not a.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        if speak.daemon_start_command() and not speak.daemon_up():
            # Start the local voice daemon now, so the first reply does not wait for it.
            print("  starting the local voice daemon")
            threading.Thread(target=speak.ensure_daemon, daemon=True).start()

        def stop(*_):                       # SIGTERM, and Ctrl+Break on Windows: same as Ctrl+C
            raise KeyboardInterrupt
        for name in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), stop)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.api.practice.stop_all()
            srv.api.stop_system_speech()
            srv.server_close()
            print("stopped")
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
