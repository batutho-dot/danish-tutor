#!/usr/bin/env python3
"""Practice sessions in the local app: the tutor runs on the Anthropic API (dansk_tutor.py).

The app server (dansk_app.py) owns one PracticeManager, which runs at most one session at a
time. Each learner line becomes one streamed API turn in a worker thread; the browser
long-polls for events. The system prompt is built from skills/dansk/session-rules.md, the
runner rules below, the learner's settings, the due items and the known words.

The reply stream is filtered before anything reaches the browser:
  <listen>...</listen>   a hidden listening sentence: removed from the text, sent as its own
                         event so the browser can play it without showing it
  <fix>{json}</fix>      a gentle live correction of the learner's last line: removed, sent as
                         a "fix" event, and kept to be saved as an error
  ```json ... ```        the end-of-session payload: removed, checked and saved exactly as
                         `dansk_db.py record` does, in one transaction
  signal lines           the turn signals from the rules (lines starting with the microphone,
                         speaker, hourglass or check mark): removed, sent as a status event
The filter works on any split of the stream into chunks. Standard library only; the API
client is imported by dansk_tutor.py only when a session starts.
"""
from __future__ import annotations

import json
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dansk_db  # noqa: E402
import dansk_tutor  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RULES = ROOT / "skills" / "dansk" / "session-rules.md"
if not RULES.is_file():                     # installed package: the rules ship as rules/
    RULES = HERE / "rules" / "session-rules.md"
MODES = {
    "chat": "Speaking: a casual chat (about 15 minutes)",
    "short": "Short chat (about 5 minutes)",
    "listen": "Listening drill (about 8 minutes)",
    "words": "Learn new words (ten words, about 10 minutes)",
}
HEARTBEAT_TIMEOUT = 90          # seconds without a poll from the browser: the tab is gone
MAX_MESSAGE = 4000
DUE_LIMIT = 40
TURN_EFFORT = "low"             # conversational turns
WRAP_EFFORT = "medium"          # the end-of-session payload

RUNNER_RULES = """\
# Running inside the danish-tutor app

You are the Danish tutor in the learner's local danish-tutor app. The learner speaks (the
browser transcribes) or types; your replies appear in a conversation window and are read
aloud. You have no tools and need none: everything you need is below.

- Each learner message starts with a note from the app in square brackets, for example
  `[app: 6 min in, voice]`. It tells you the time so far and how the learner answered. It is
  not from the learner: never answer it or mention it.
- End every reply with exactly one turn signal line, copied exactly from the rules, on its own
  line. The app turns it into a status label and never shows it.
- Live corrections use `<fix>` (see the rules). Hidden listening sentences use `<listen>`
  (see the rules). The app removes both from what the learner sees.

## Saving

When the session is over (after the wrap-up, or when the app says the learner pressed End
session), output the payload as one fenced block that starts with ```json and ends with ```,
after the wrap-up, followed by the hourglass signal line. The app removes the block from the
chat, checks it exactly as `dansk_db.py record` does and saves it in one transaction. It then
tells you the saved line or the list of problems. On problems, send the whole corrected
payload again in the same form, with nothing else but the hourglass signal line. Once the app
tells you it saved, reply with only one short warm closing line in Danish and the finished
signal. Do not repeat the saved line; the app shows it.
"""

FIX_KEYS = ("said", "correct", "why", "category", "pattern_id", "severity")


def build_prompt(mode: str, topic: str | None, cfg: dict, due: dict, words: list[dict],
                 today: str) -> str:
    """The tutor's system prompt: the shared rules, the app's runner rules, then the data.
    It stays the same for the whole session, so it is cached after the first turn."""
    rules = RULES.read_text(encoding="utf-8")
    learner = due.get("learner") or {}
    settings = {"learner_name": cfg.get("learner_name") or "",
                "level": cfg.get("level") or learner.get("level") or "A2",
                "target_level": cfg.get("target_level") or learner.get("target_level") or "B2",
                "goal": cfg.get("goal") or "everyday conversation",
                "support_language": cfg.get("support_language")
                or learner.get("support_language") or "English"}
    if mode == "words":
        how = (f"The learner chose the topic: {topic}" if topic
               else "The learner asked you to choose the topic.")
        mode_line = f"{MODES[mode]}. {how}"
    else:
        mode_line = MODES[mode]
    known = "\n".join(f"- {w['headword']}" + (f" ({w['gloss']})" if w.get("gloss") else "")
                      for w in words) or "(none yet)"
    data = {k: due[k] for k in ("first_session", "due_count", "due_items", "error_patterns")}
    return "\n\n".join([
        rules.strip(),
        RUNNER_RULES.strip(),
        "# This session\n\n"
        f"- Today: {today}\n- Mode: {mode_line}\n"
        f"- Settings: {json.dumps(settings, ensure_ascii=False)}",
        "# Due items and error patterns\n\n```\n"
        + json.dumps(data, ensure_ascii=False, indent=1) + "\n```",
        "# Headwords the learner already has\n\n" + known,
    ]) + "\n"


SIGNAL_START = ("\U0001f3a4", "\U0001f50a", "⏳", "✅")   # microphone, speaker, hourglass, check

TOPIC_IDEAS = [
    (("work", "job", "arbejde", "office", "career"),
     ["Your working day", "Meetings and colleagues", "Getting to work"]),
    (("travel", "rejse", "holiday", "ferie", "trip"),
     ["Booking a trip", "At the train station", "Asking for directions"]),
    (("study", "studie", "university", "school", "uni"),
     ["Lectures and exams", "Student life", "Your study group"]),
    (("family", "familie", "children", "kids"),
     ["Your family", "Weekend plans", "Cooking at home"]),
    (("shop", "food", "mad", "restaurant", "cafe"),
     ["Food and shopping", "At a cafe", "Cooking dinner"]),
]
DEFAULT_TOPICS = ["Food and shopping", "Your home", "Weekend plans"]


def topic_ideas(goal: str) -> list[str]:
    """Three topic suggestions for the new-words picker, from words in the `goal` setting."""
    g = (goal or "").lower()
    for keys, ideas in TOPIC_IDEAS:
        if any(k in g for k in keys):
            return ideas
    return DEFAULT_TOPICS


# ---------------------------------------------------------------- stream filter

class StreamFilter:
    """Turns reply text, in chunks split anywhere, into events in order:
    ("text", s), ("listen", sentence), ("fix", raw json), ("payload", raw json),
    ("signal", kind, detail)."""

    MARKERS = (("<listen>", "</listen>", "listen"), ("<fix>", "</fix>", "fix"),
               ("```json", "```", "payload"))

    def __init__(self):
        self.buf = ""
        self.inside: tuple[str, str, str] | None = None
        self.line_mode = "start"      # start | pass | hold
        self.held = ""

    # stage 1: markers
    def feed(self, chunk: str) -> list[tuple]:
        out: list[tuple] = []
        self.buf += chunk
        while self.buf:
            if self.inside is None:
                hits = [(self.buf.find(o), o, c, k) for o, c, k in self.MARKERS if o in self.buf]
                if hits:
                    i, o, c, k = min(hits)
                    self._text(self.buf[:i], out)
                    self.buf = self.buf[i + len(o):]
                    self.inside = (o, c, k)
                    continue
                keep = self._partial_opener()
                self._text(self.buf[:len(self.buf) - keep], out)
                self.buf = self.buf[len(self.buf) - keep:]
                break
            _, close, kind = self.inside
            j = self.buf.find(close)
            if j < 0:
                break
            self._marker(kind, self.buf[:j], out)
            self.buf = self.buf[j + len(close):]
            self.inside = None
        return out

    def flush(self) -> list[tuple]:
        out: list[tuple] = []
        if self.inside is not None:
            self._marker(self.inside[2], self.buf, out)      # unclosed: never shown
        else:
            self._text(self.buf, out)
        self.buf, self.inside = "", None
        if self.line_mode == "hold":
            out.append(classify_signal(self.held))
        elif self.held:
            out.append(("text", self.held))
        self.held, self.line_mode = "", "start"
        return out

    def _partial_opener(self) -> int:
        best = 0
        for o, _, _ in self.MARKERS:
            for k in range(min(len(o) - 1, len(self.buf)), 0, -1):
                if self.buf.endswith(o[:k]):
                    best = max(best, k)
                    break
        return best

    @staticmethod
    def _marker(kind: str, body: str, out: list):
        body = body.strip()
        if body:
            out.append((kind, body))

    # stage 2: signal lines, held back until the line is complete
    def _text(self, t: str, out: list):
        emit = []
        for ch in t:
            if self.line_mode == "pass":
                emit.append(ch)
                if ch == "\n":
                    self.line_mode = "start"
            elif self.line_mode == "start":
                if ch == "\n":
                    emit.append(self.held + ch)
                    self.held = ""
                elif ch.isspace():
                    self.held += ch
                elif ch in SIGNAL_START:
                    self.held = ch
                    self.line_mode = "hold"
                else:
                    emit.append(self.held + ch)
                    self.held = ""
                    self.line_mode = "pass"
            else:                                   # hold
                if ch == "\n":
                    if emit:
                        out.append(("text", "".join(emit)))
                        emit = []
                    out.append(classify_signal(self.held))
                    self.held = ""
                    self.line_mode = "start"
                else:
                    self.held += ch
        if emit:
            out.append(("text", "".join(emit)))


LISTEN_COUNTER = re.compile(r"(\d+)\s+af\s+(\d+)")


def classify_signal(line: str) -> tuple:
    line = line.strip()
    if line.startswith("✅"):
        return ("signal", "done", "")
    if line.startswith("⏳"):
        return ("signal", "saving", "")
    if line.startswith("\U0001f50a"):
        if "Samme" in line or "langsommere" in line:
            return ("signal", "replay", "")
        m = LISTEN_COUNTER.search(line)
        return ("signal", "listening", f"{m[1]} of {m[2]}" if m else "")
    return ("signal", "your_turn", "")


# ---------------------------------------------------------------- one session

class PracticeError(Exception):
    """A request the session cannot take now: becomes a 409 with this message."""


def parse_fix(body: str) -> dict | None:
    """A <fix> body: JSON with said, correct, why and optionally category, pattern_id,
    severity. Anything else is dropped (never shown)."""
    try:
        d = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    d = {k: d[k].strip() for k in FIX_KEYS if isinstance(d.get(k), str) and d[k].strip()}
    if not d.get("said") or not d.get("correct"):
        return None
    return d


def fix_pattern_id(fix: dict) -> str:
    pid = (fix.get("pattern_id") or "").lower()
    if dansk_db.PATTERN_ID.match(pid or "-"):
        return pid
    words = re.sub(r"[^a-z0-9]+", "_", dansk_db.dansk_text.fold(fix["correct"]).lower()).strip("_")
    return ("fix_" + words)[:60].rstrip("_") or "fix"


def merge_fixes(payload, fixes: list[dict]):
    """Every live correction is also an error in the payload: add the ones the model left
    out (matched on said and correct)."""
    if not isinstance(payload, dict) or not fixes:
        return payload
    errs = payload.get("errors")
    if errs is None:
        errs = []
    if not isinstance(errs, list):
        return payload
    have = {(e.get("said"), e.get("correct")) for e in errs if isinstance(e, dict)}
    for f in fixes:
        if (f["said"], f["correct"]) in have:
            continue
        sev = f.get("severity") if f.get("severity") in dansk_db.SEVERITIES else "minor"
        errs.append({"pattern_id": fix_pattern_id(f), "category": f.get("category") or "grammar",
                     "said": f["said"], "correct": f["correct"],
                     "context": f.get("why") or "", "severity": sev})
        have.add((f["said"], f["correct"]))
    return {**payload, "errors": errs}


class Session:
    def __init__(self, manager: "PracticeManager", mode: str, topic: str | None, system: str):
        self.m = manager
        self.id = secrets.token_hex(8)
        self.mode = mode
        self.topic = topic
        self.system = system
        self.started = time.monotonic()
        self.last_poll = time.monotonic()
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.state = "starting"          # starting, replying, waiting, saved, finished, ended
        self.history: list[dict] = []
        self.fixes: list[dict] = []
        self.input_modes: set[str] = set()
        self.saved_line: str | None = None
        self.payload_file: str | None = None
        self.end_requested = False
        self.last_problems: list[str] = []
        self.cancelled = False

    # ---- events

    def emit(self, type_: str, **data):
        with self.cond:
            self.events.append({"seq": len(self.events) + 1, "type": type_, **data})
            self.cond.notify_all()

    def set_state(self, state: str):
        with self.cond:
            self.state = state
            self.cond.notify_all()
        self.emit("state", state=state)

    def wait_events(self, after: int, timeout: float) -> list[dict]:
        self.last_poll = time.monotonic()
        with self.cond:
            if len(self.events) <= after and self.state not in ("ended", "finished"):
                self.cond.wait(timeout)
            return self.events[after:]

    def minutes(self) -> int:
        return max(1, round((time.monotonic() - self.started) / 60))

    # ---- one turn

    def turn(self, text: str, effort: str = TURN_EFFORT):
        """Send one user message and stream the reply in a worker thread."""
        self.history.append({"role": "user", "content": text})
        self.set_state("replying")
        threading.Thread(target=self._run, args=(effort,), daemon=True).start()

    def _run(self, effort: str):
        filt = StreamFilter()
        shown: list[str] = []
        payloads: list[str] = []

        def process(evs):
            for ev in evs:
                if ev[0] == "text":
                    shown.append(ev[1])
                    self.emit("text", text=ev[1])
                elif ev[0] == "listen":
                    self.emit("listen", sentence=ev[1])
                elif ev[0] == "fix":
                    fix = parse_fix(ev[1])
                    if fix:
                        self.fixes.append(fix)
                        self.emit("fix", said=fix["said"], correct=fix["correct"],
                                  why=fix.get("why", ""))
                elif ev[0] == "payload":
                    payloads.append(ev[1])
                elif ev[0] == "signal":
                    self.emit("signal", signal=ev[1], detail=ev[2])

        try:
            content = self.m.backend.stream_reply(
                self.system, list(self.history), effort,
                lambda chunk: process(filt.feed(chunk)), lambda: self.cancelled)
        except dansk_tutor.TutorError as e:
            if e.kind == "cancelled" or self.cancelled:
                return
            self.history.pop()                    # the learner can send the line again
            self.emit("discard")
            self.emit("error", message=e.message, kind=e.kind)
            self.set_state("waiting" if self.saved_line is None else "saved")
            return
        except Exception as e:                     # never let the worker die silently
            self.history.pop()
            self.emit("discard")
            self.emit("error", message=f"internal error: {type(e).__name__}", kind="internal")
            self.set_state("waiting")
            return
        if self.cancelled:
            return
        process(filt.flush())
        self.history.append({"role": "assistant", "content": content})
        self.emit("turn_end", text="".join(shown).strip())
        if payloads:
            self._save(payloads[-1])
            return
        if self.state == "replying" and self.saved_line is not None:
            self.set_state("finished")             # the closing line after the save
            return
        elif self.end_requested and self.saved_line is None:
            self.last_problems = ["The tutor's reply held no payload."]
            self.emit("save_error", problems=self.last_problems, path=None)
        if self.state == "replying":
            self.set_state("waiting" if self.saved_line is None else "saved")

    # ---- saving

    def _save(self, raw: str):
        try:
            payload = merge_fixes(json.loads(raw), self.fixes)
        except json.JSONDecodeError as e:
            code, lines = 1, ["not saved: payload is not valid JSON", f"  {e}"]
            payload = None
        else:
            code, lines = self.m.record(payload)
        if code == 0:
            self.saved_line = lines[0]
            self.payload_file = None
            self.emit("saved", line=lines[0], lines=lines)
            self.turn(f"[app] The session was saved: {lines[0]}. Reply with your one closing "
                      "line and the finished signal.")
            return
        path = Path(tempfile.gettempdir()) / f"dansk-payload-{self.m.today()}-{self.id}.json"
        try:
            text = json.dumps(payload, ensure_ascii=False, indent=1) if payload is not None else raw
            path.write_text(text, encoding="utf-8")
            self.payload_file = str(path)
        except OSError:
            self.payload_file = None
        self.last_problems = lines
        self.emit("save_error", problems=lines, path=self.payload_file)
        self.set_state("waiting")

    # ---- learner actions

    def _ready(self):
        if self.state in ("ended", "finished"):
            raise PracticeError("this session has ended")
        if self.state in ("replying", "starting"):
            raise PracticeError("the tutor is still replying")

    def send(self, text: str, via: str):
        self._ready()
        self.input_modes.add(via)
        self.emit("user", text=text, via=via)
        self.turn(f"[app: {self.minutes()} min in, {via}] {text}")

    def input_mode(self) -> str:
        if self.input_modes == {"voice"}:
            return "voice"
        return "mixed" if "voice" in self.input_modes else "typed"

    def facts(self) -> str:
        return (f"Use date {self.m.today()}, duration_minutes {self.minutes()} and input_mode "
                f"{self.input_mode()}.")

    def end(self):
        self._ready()
        if self.saved_line is not None:
            raise PracticeError("this session is already saved")
        self.end_requested = True
        self.turn(f"[app: {self.minutes()} min in] The learner pressed End session. Wrap up "
                  "now: skip anything not done yet, give the short wrap-up, then the payload. "
                  + self.facts(), WRAP_EFFORT)

    def retry_save(self):
        self._ready()
        if self.saved_line is not None:
            raise PracticeError("nothing to save again")
        problems = "\n".join(self.last_problems or ["no payload was sent"])
        self.end_requested = True
        self.turn("[app] The payload was not saved. Problems:\n" + problems +
                  "\nSend the whole corrected payload again, in one ```json block. "
                  + self.facts(), WRAP_EFFORT)

    def stop(self):
        self.cancelled = True
        if self.state not in ("ended", "finished"):
            self.set_state("ended")

    def snapshot(self) -> dict:
        return {"id": self.id, "mode": self.mode, "topic": self.topic, "state": self.state,
                "saved_line": self.saved_line, "payload_file": self.payload_file,
                "events": len(self.events)}


# ---------------------------------------------------------------- the manager

class PracticeManager:
    """At most one session at a time. `record` saves a payload the way `dansk_db.py record`
    does, under the app's write lock."""

    def __init__(self, db: Path, today, lock: threading.Lock, cfg: dict | None = None,
                 backend=None):
        self.db = db
        self.today = today
        self.lock = lock
        self.cfg = cfg if cfg is not None else dansk_db.load_config()
        self.backend = backend if backend is not None else dansk_tutor.load_backend()
        self.current: Session | None = None
        self.mlock = threading.Lock()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def status(self) -> dict:
        s = self.current
        st = self.backend.status()
        return {"available": bool(st.get("ready")), "problem": st.get("problem"),
                "message": st.get("message") or "", "model": st.get("model"),
                "goal": self.cfg.get("goal") or "everyday conversation",
                "topics": topic_ideas(self.cfg.get("goal") or ""), "modes": MODES,
                "session": s.snapshot() if s else None}

    def record(self, payload) -> tuple[int, list[str]]:
        with self.lock:
            return dansk_db.record_payload(self.db, payload, self.cfg)

    def start(self, mode: str, topic: str | None) -> Session:
        st = self.backend.status()
        if not st.get("ready"):
            raise PracticeError(st.get("message") or "the tutor is not available")
        with self.mlock:
            if self.current is not None and self.current.state not in ("ended", "finished"):
                raise PracticeError("a practice session is already running; end it first")
            con = dansk_db.connect(self.db)
            try:
                due = dansk_db.due_report(con, self.today(), DUE_LIMIT)
                words = dansk_db.headwords(con)
            finally:
                con.close()
            s = Session(self, mode, topic,
                        build_prompt(mode, topic, self.cfg, due, words, self.today()))
            first = f"[app: 0 min in] Start the session now. Mode: {MODES[mode]}."
            if mode == "words":
                first += (f" The learner's topic: {topic}" if topic
                          else " The learner asked you to choose the topic.")
            self.current = s
            s.turn(first)
            return s

    def get(self, sid: str) -> Session:
        s = self.current
        if s is None or s.id != sid:
            raise KeyError(sid)
        return s

    def stop_all(self):
        s = self.current
        if s is not None:
            s.stop()

    def _watchdog(self):
        while True:
            time.sleep(5)
            s = self.current
            if s is not None and s.state not in ("ended", "finished") and \
                    time.monotonic() - s.last_poll > HEARTBEAT_TIMEOUT:
                s.emit("error", message="The app page was closed, so the session was stopped.",
                       kind="closed")
                s.stop()
