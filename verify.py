#!/usr/bin/env python3
"""verify.py: check danish-tutor end to end and print PASS or FAIL from real runs.

    python verify.py

Steps: every .py compiles; each skill under skills/ has frontmatter whose name matches its
folder and a description; the dashboard builds (JSON mode) from example-data into a temporary
folder and the page holds fixed strings from the example data; word notes are matched to their
spaced-repetition items with the expected due dates; the SM-2 scheduler gives hand-computed
intervals and easiness factors; the README is at most 550 words; no file holds a banned string
or an audio file; the plugin manifests parse and agree; the unit tests pass; example-data
imported into a temporary database builds the same dashboard summary and due dates; a session
payload recorded into a temporary database can be read back, and a bad payload writes
nothing; the committed app build in app/dist is complete (every file index.html references,
THIRD_PARTY_NOTICES.txt) and scripts/dansk_app.py serves it from a temporary database with
its token check; a practice session against the scripted tutor in tests/fake_tutor.py
keeps the live correction and the listening sentence out of the chat text and saves its
payload; the repository is unchanged afterwards. app/node_modules is not needed, and the
Anthropic API is never called.

SM-2 rules: Wozniak (1990), "SuperMemo 2: Algorithm",
https://super-memory.com/english/ol/sm2.htm.

Needs only the Python standard library. Writes nothing inside the repository: every database
and page goes to a temporary folder, and child processes run without writing bytecode.
"""
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TODAY = "2026-11-06"           # fixed "today" so due counts never drift
sys.dont_write_bytecode = True


class Fail(Exception):
    pass


def files(exts=None):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # node_modules is gitignored (app/node_modules): installed packages, not the repository
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", ".venv", "data", "node_modules")]
        for f in filenames:
            if exts is None or f.endswith(exts):
                yield os.path.join(dirpath, f)


def snapshot():
    return {os.path.relpath(p, ROOT): (os.path.getsize(p), os.path.getmtime(p)) for p in files()}


def step_compile():
    n = 0
    for p in files((".py",)):
        try:
            compile(open(p, encoding="utf-8").read(), p, "exec")
        except SyntaxError as e:
            raise Fail(f"{os.path.relpath(p, ROOT)}:{e.lineno}: {e.msg}")
        n += 1
    return f"{n} files"


def step_frontmatter():
    skills = []
    for d in sorted(os.listdir(os.path.join(ROOT, "skills"))):
        p = os.path.join(ROOT, "skills", d, "SKILL.md")
        if os.path.isfile(p):
            skills.append((d, p))
    if not skills:
        raise Fail("no skills/*/SKILL.md found")
    for folder, p in skills:
        text = open(p, encoding="utf-8").read()
        m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
        if not m:
            raise Fail(f"skills/{folder}/SKILL.md: no frontmatter")
        name = re.search(r"^name:\s*(\S+)", m.group(1), re.M)
        if not name or name.group(1) != folder:
            raise Fail(f"skills/{folder}/SKILL.md: name does not match folder")
        if not re.search(r"^description:\s*\S", m.group(1), re.M):
            raise Fail(f"skills/{folder}/SKILL.md: no description")
    return f"{len(skills)} skill(s)"


def child_env(tmp):
    """Environment for child processes: no bytecode, UTF-8, and settings and database paths
    pointing into the temp folder so no real learner file is ever read."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               DANISH_TUTOR_CONFIG=os.path.join(tmp, "no-config.json"),
               DANISH_TUTOR_DB=os.path.join(tmp, "unused.db"),
               CLV_SOCKET=os.path.join(tmp, "no-voice.sock"), CLV_PORT=str(closed_port()))
    for k in ("DANSK_DATA_DIR", "DANSK_WORDS_DIR", "DANISH_TUTOR_BACKEND",
              "DANISH_TUTOR_ANTHROPIC_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    return env


def closed_port():
    """A port nothing listens on, so no step can reach a real voice daemon."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_py(args, tmp, stdin=None):
    return subprocess.run([PY, "-B", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=child_env(tmp), cwd=tmp, input=stdin)


def load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *parts))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def step_dashboard():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "dash.html")
        env = child_env(tmp)
        r = subprocess.run([PY, "-B", os.path.join(ROOT, "dashboard", "build_dashboard.py"),
                            "--data", os.path.join(ROOT, "example-data"), "--out", out,
                            "--today", TODAY],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, cwd=tmp)
        if r.returncode:
            raise Fail(f"exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        want_line = f"13 word notes, 1 grammar notes, 16 tracked items, 15 due on {TODAY}"
        if want_line not in r.stdout:
            raise Fail(f"summary line missing, got: {r.stdout.strip()}")
        if not os.path.isfile(out):
            raise Fail("no page written")
        page = open(out, encoding="utf-8").read()
        for want in ('"head": "nøgle"', '"gloss": "breakfast"', "example-session-002"):
            if want not in page:
                raise Fail(f"page lacks {want}")
        if "/*__DATA__*/null" in page:
            raise Fail("data placeholder was not replaced")
    return "built in a temp folder, summary line and fixed strings present"


def step_sm2_match():
    spec = importlib.util.spec_from_file_location(
        "build_dashboard", os.path.join(ROOT, "dashboard", "build_dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ex = Path(ROOT, "example-data")
    data = mod.build_data(ex, ex / "words", date.fromisoformat(TODAY))
    by_head = {w["head"]: w for w in data["words"]}
    checks = [("nøgle", "2026-11-05", True), ("morgenmad", "2026-11-10", False),
              ("at spise", "2026-11-05", True), ("ikke i bisætninger", "2026-11-03", True)]
    for head, due, overdue in checks:
        w = by_head.get(head)
        if w is None:
            raise Fail(f"no word note for {head}")
        if w["due"] != due or w["overdue"] != overdue:
            raise Fail(f"{head}: due {w['due']} overdue {w['overdue']}, expected {due} {overdue}")
    if mod.fold("Værelse") != "vaerelse":
        raise Fail("fold('Værelse') should give vaerelse")
    return f"{len(checks)} notes matched to their items"


def step_scheduling():
    """Hand-computed SM-2 values (Wozniak 1990): a new item answered 5, 5, 5 gets intervals
    1, 6, ceil(6 * 2.8) = 17 with EF 2.6, 2.7, 2.8; a 2 then resets to 1 day with EF unchanged;
    repeated 3s (EF - 0.14 each) stop at the 1.3 floor."""
    db = load("dansk_db", "scripts", "dansk_db.py")
    ef, i, n = 2.5, 0, 0
    for q, want in [(5, (2.6, 1, 1)), (5, (2.7, 6, 2)), (5, (2.8, 17, 3)), (2, (2.8, 1, 0))]:
        ef, i, n = db.sm2(q, ef, i, n)
        if (round(ef, 6), i, n) != want:
            raise Fail(f"q={q}: got EF {ef}, interval {i}, repetitions {n}; expected {want}")
    ef, i, n = 2.5, 0, 0
    for _ in range(12):
        ef, i, n = db.sm2(3, ef, i, n)
    if ef != 1.3:
        raise Fail(f"EF after twelve 3s is {ef}, expected the 1.3 floor")
    if db.mastery(7) != 5 or db.mastery(2) != 2:
        raise Fail("mastery should be min(5, repetitions)")
    return "intervals 1, 6, 17 then reset to 1 with EF 2.8 kept; EF floor 1.3"


def step_readme():
    words = len(open(os.path.join(ROOT, "README.md"), encoding="utf-8").read().split())
    if words > 550:
        raise Fail(f"README.md has {words} words, limit 550")
    return f"{words} words"


# Banned strings, built from pieces so this file does not contain them itself.
BANNED = [
    (re.compile("ba" + "tu", re.I), "first name"),
    (re.compile("tho" + "ms", re.I), "surname"),
    (re.compile(r"\bNo" + r"lan\b"), "voice name"),
    (re.compile(r"\bI" + r"da\b"), "voice name"),
    (re.compile("one" + "drive", re.I), "cloud folder"),
    (re.compile(r"\bS" + r"DU\b"), "university"),
    (re.compile("oden" + "se", re.I), "city"),
    (re.compile("llm ?" + "wiki", re.I), "vault name"),
    (re.compile(r"\bAI " + r"OS\b"), "vault folder"),
    (re.compile(r"[A-Za-z]:[\\/]+" + "Users", re.I), "Windows home path"),
    (re.compile("/" + "Users/"), "macOS home path"),
    (re.compile(r"[\w.+-]+" + "@" + r"[\w-]+\.[A-Za-z]{2,}"), "email address"),
    (re.compile(r"\bsk" + r"-(ant-)?[A-Za-z0-9_-]{16,}"), "API key"),
    (re.compile("AK" + "IA[0-9A-Z]{16}"), "AWS key"),
    (re.compile("gh" + "p_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(chr(0x2014)), "em dash"),
]
# Narrow exemptions: the author / owner "name" line of the two plugin manifests, and the
# public repository slug used in install commands. Built from pieces like BANNED.
MANIFESTS = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json")
MANIFEST_HOLDER = re.compile(r'^\s*"(author|owner)": \{"name": "[^"]*"\},?\s*$')
REPO_SLUG = "ba" + "tutho-dot/danish-tutor"
# The generated third-party licence file quotes other authors' copyright lines, some with an
# e-mail address. Only that rule, only that file.
NOTICES = "app/dist/THIRD_PARTY_NOTICES.txt"
AUDIO = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aiff")


def step_banned():
    hits = []
    for p in files():
        rel = os.path.relpath(p, ROOT)
        if p.lower().endswith(AUDIO):
            hits.append(f"{rel}: audio file")
            continue
        try:
            text = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        posix = Path(rel).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            if rel == "LICENSE" and n == 1 and line.startswith("Required Notice: Copyright (c)"):
                continue                       # the licence holder's notice line stays as written
            if posix in MANIFESTS and MANIFEST_HOLDER.match(line):
                continue                       # the plugin's author / owner field, same holder
            line = line.replace(REPO_SLUG, "")  # the public repository name in install lines
            for rx, what in BANNED:
                if posix == NOTICES and what == "email address":
                    continue                   # third-party copyright lines, kept verbatim
                if rx.search(line):
                    hits.append(f"{rel}:{n} {what}")
    if hits:
        raise Fail("; ".join(hits[:8]) + (f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""))
    return "none"


def step_manifest():
    base = os.path.join(ROOT, ".claude-plugin")
    try:
        with open(os.path.join(base, "plugin.json"), encoding="utf-8") as f:
            plugin = json.load(f)
        with open(os.path.join(base, "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise Fail(f"manifest does not parse: {e}")
    entries = [p for p in market.get("plugins", []) if p.get("name") == plugin.get("name")]
    if plugin.get("name") != "danish-tutor" or market.get("name") != "danish-tutor" or not entries:
        raise Fail("plugin.json name and marketplace.json names do not match")
    if entries[0].get("version") != plugin.get("version"):
        raise Fail("versions differ between plugin.json and marketplace.json")
    if not os.path.isfile(os.path.join(ROOT, "skills", "dansk", "SKILL.md")):
        raise Fail("skills/dansk/SKILL.md missing")
    return f"{plugin['name']} {plugin.get('version')}, both manifests parse, skills/dansk present"


def step_unittests():
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([PY, "-B", "-m", "unittest", "discover", "-s", "tests"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=child_env(tmp), cwd=ROOT)
    lines = (r.stdout + r.stderr).strip().splitlines()
    ran = next((x for x in lines if x.startswith("Ran ")), "no tests ran")
    if r.returncode:
        raise Fail(f"exit {r.returncode}: " + " | ".join(lines[-12:]))
    return f"{ran}, OK"


DUE_CHECKS = [("nøgle", "2026-11-05", True), ("morgenmad", "2026-11-10", False),
              ("at spise", "2026-11-05", True), ("ikke i bisætninger", "2026-11-03", True)]


def step_db_import():
    with tempfile.TemporaryDirectory() as tmp:
        dbf = os.path.join(tmp, "import.db")
        r = run_py([os.path.join(ROOT, "scripts", "import_fluent.py"),
                    "--data", os.path.join(ROOT, "example-data"), "--db", dbf], tmp)
        if r.returncode:
            raise Fail(f"import exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        out = os.path.join(tmp, "dash.html")
        r = run_py([os.path.join(ROOT, "dashboard", "build_dashboard.py"), "--db", dbf,
                    "--out", out, "--today", TODAY], tmp)
        if r.returncode:
            raise Fail(f"dashboard exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        want_line = f"13 word notes, 1 grammar notes, 16 tracked items, 15 due on {TODAY}"
        if want_line not in r.stdout:
            raise Fail(f"summary line missing, got: {r.stdout.strip()}")
        with open(out, encoding="utf-8") as f:
            page = f.read()
        for want in ('"head": "nøgle"', '"gloss": "breakfast"', "example-session-002"):
            if want not in page:
                raise Fail(f"page lacks {want}")
        dash = load("build_dashboard", "dashboard", "build_dashboard.py")
        words = dash.build_data_db(Path(dbf), date.fromisoformat(TODAY))["words"]
        by_head = {w["head"]: w for w in words}
        for head, due, overdue in DUE_CHECKS:
            w = by_head.get(head)
            if w is None or w["due"] != due or w["overdue"] != overdue:
                got = (w["due"], w["overdue"]) if w else None
                raise Fail(f"{head}: {got}, expected {due} {overdue}")
    return f"same summary line, {len(DUE_CHECKS)} due dates match JSON mode"


def step_record():
    payload = {
        "date": "2026-11-07", "duration_minutes": 5, "size": "small", "input_mode": "typed",
        "topic": "invented check", "skills": ["speaking"],
        "new_words": [{"headword": "værelse", "gloss": "room", "example": "Mit værelse er lille."}],
        "listening": [{"sentence": "Huset har tre værelser.", "result": "missed"}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        dbf = os.path.join(tmp, "record.db")
        script = os.path.join(ROOT, "scripts", "dansk_db.py")
        bad = dict(payload, size="huge")
        r = run_py([script, "record", "--db", dbf], tmp, json.dumps(bad, ensure_ascii=False))
        if r.returncode != 1:
            raise Fail(f"bad payload: exit {r.returncode}, expected 1: {r.stdout.strip()}")
        r = run_py([script, "record", "--db", dbf], tmp, json.dumps(payload, ensure_ascii=False))
        if r.returncode:
            raise Fail(f"record exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        want = "saved session-2026-11-07, 0 reviews, 1 new words, 0 errors; 1 items due tomorrow"
        if want not in r.stdout:
            raise Fail(f"saved line missing, got: {r.stdout.strip()}")
        con = sqlite3.connect(dbf)              # re-open from scratch
        try:
            sessions = con.execute("SELECT id FROM sessions").fetchall()
            word = con.execute("SELECT id, gloss FROM words WHERE headword = ?",
                               ("værelse",)).fetchone()
            ex = con.execute("SELECT sentence FROM examples").fetchall()
            item = con.execute("SELECT due_date, easiness_factor FROM items WHERE id = ?",
                               ("vocab_vaerelse",)).fetchone()
        finally:
            con.close()
        if sessions != [("session-2026-11-07",)]:
            raise Fail(f"sessions {sessions}: the bad payload wrote something, or the good one did not")
        if not word or word[1] != "room" or ex != [("Mit værelse er lille.",)]:
            raise Fail(f"word or example not stored: {word} {ex}")
        if item != ("2026-11-08", 2.5):
            raise Fail(f"vocab_vaerelse is {item}, expected due 2026-11-08 with EF 2.5")
    return "word, example, item due date and session read back; bad payload exit 1, nothing written"


def step_app_build():
    """The committed build in app/dist is complete, and the server serves it against a
    temporary database: index.html with the token, 403 without it, the summary with it."""
    dist = Path(ROOT, "app", "dist")
    index = dist / "index.html"
    if not index.is_file():
        raise Fail("app/dist/index.html missing: cd app && npm ci && npm run build")
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    local = [r for r in refs if not re.match(r"^(?:[a-z]+:|//|#)", r)]
    if not any(r.endswith(".js") for r in local):
        raise Fail("index.html references no script")
    for r in local:
        if not (dist / r.lstrip("./")).is_file():
            raise Fail(f"index.html references {r}, which is not in app/dist")
    if "__DANSK_TOKEN__" not in html:
        raise Fail("index.html lacks the token placeholder")
    notices = dist / "THIRD_PARTY_NOTICES.txt"
    if not notices.is_file() or "recharts" not in notices.read_text(encoding="utf-8"):
        raise Fail("app/dist/THIRD_PARTY_NOTICES.txt missing or incomplete")

    import http.client
    import threading
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    app = load("dansk_app", "scripts", "dansk_app.py")
    with tempfile.TemporaryDirectory() as tmp:
        dbf = Path(tmp, "app.db")
        r = run_py([os.path.join(ROOT, "scripts", "import_fluent.py"),
                    "--data", os.path.join(ROOT, "example-data"), "--db", str(dbf)], tmp)
        if r.returncode:
            raise Fail(f"import exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        srv = app.make_server(dbf, dist, port=0, today=TODAY, quiet=True, cfg={})
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            def get(path, token=True):
                c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
                h = {"Host": f"127.0.0.1:{srv.port}"}
                if token:
                    h["X-Dansk-Token"] = srv.token
                c.request("GET", path, headers=h)
                resp = c.getresponse()
                body = resp.read()
                c.close()
                return resp.status, body
            status, body = get("/", token=False)
            if status != 200 or srv.token.encode() not in body:
                raise Fail(f"/ gave {status} or lacks the token")
            js = next(x for x in local if x.endswith(".js"))
            if get("/" + js.lstrip("./"), token=False)[0] != 200:
                raise Fail(f"{js} not served")
            if get("/api/summary", token=False)[0] != 403:
                raise Fail("/api/summary without the token was not refused")
            status, body = get("/api/summary")
            s = json.loads(body)
            if status != 200 or (s["words"], s["grammar"], s["items"], s["due"]) != (13, 1, 16, 15):
                raise Fail(f"/api/summary {status}: {body[:200]!r}")
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(5)
    return (f"{len(local)} referenced files present, notices present; served from a temp db: "
            "index with token, 403 without it, summary 13 words, 16 items, 15 due")


def step_practice():
    """A short practice session against the scripted fake tutor (tests/fake_tutor.py, no
    network): the live correction and the hidden sentence arrive as their own events and
    never in the chat text, the payload is saved with the correction as an error, the
    session finishes."""
    import http.client
    import threading
    import time
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    app = load("dansk_app", "scripts", "dansk_app.py")
    fake = os.path.join(ROOT, "tests", "fake_tutor.py")
    saved_env = {k: os.environ.get(k) for k in ("DANISH_TUTOR_BACKEND", "FAKE_TUTOR_SCENARIO",
                                                 "FAKE_TUTOR_DELAY")}
    os.environ["DANISH_TUTOR_BACKEND"] = fake
    os.environ.pop("FAKE_TUTOR_SCENARIO", None)
    os.environ.pop("FAKE_TUTOR_DELAY", None)
    app.POLL_SECONDS = 2
    with tempfile.TemporaryDirectory() as tmp:
        dbf = Path(tmp, "practice.db")
        r = run_py([os.path.join(ROOT, "scripts", "import_fluent.py"),
                    "--data", os.path.join(ROOT, "example-data"), "--db", str(dbf)], tmp)
        if r.returncode:
            raise Fail(f"import exit {r.returncode}: {(r.stdout + r.stderr).strip()}")
        srv = app.make_server(dbf, Path(ROOT, "app", "dist"), port=0, today=TODAY, quiet=True, cfg={})
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        events = []

        def call(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
            c.request(method, path, body=json.dumps(body) if body is not None else None,
                      headers={"Host": f"127.0.0.1:{srv.port}", "X-Dansk-Token": srv.token,
                               "Content-Type": "application/json"})
            resp = c.getresponse()
            data = json.loads(resp.read())
            c.close()
            return resp.status, data

        def until(sid, pred):
            end = time.monotonic() + 30
            while time.monotonic() < end:
                _, d = call("GET", f"/api/practice/{sid}/events?after={len(events)}")
                events.extend(d["events"])
                if pred(d["session"]):
                    return
            raise Fail(f"practice timed out in state {d['session']['state']}")

        try:
            status, s = call("POST", "/api/practice/start", {"mode": "short"})
            if status != 200:
                raise Fail(f"start gave {status}: {s}")
            sid = s["id"]
            until(sid, lambda x: x["state"] == "waiting")
            for text in ("Fordi jeg har ikke tid", "Hvor er nøglen"):
                call("POST", f"/api/practice/{sid}/message", {"text": text, "via": "typed"})
                until(sid, lambda x: x["state"] == "waiting")
            call("POST", f"/api/practice/{sid}/end")
            until(sid, lambda x: x["state"] == "finished")
            shown = "".join(e.get("text", "") for e in events if e["type"] == "text")
            listen = [e["sentence"] for e in events if e["type"] == "listen"]
            saved = [e["line"] for e in events if e["type"] == "saved"]
            if listen != ["Hvor har du lagt nøglen?"] or "nøglen" in shown:
                raise Fail(f"listening sentence not hidden: listen {listen}")
            fixes = [(e["said"], e["correct"]) for e in events if e["type"] == "fix"]
            if fixes != [("fordi jeg har ikke tid", "fordi jeg ikke har tid")] or "<fix>" in shown:
                raise Fail(f"live correction not delivered as its own event: {fixes}")
            if not saved or "1 new words, 1 errors" not in saved[0]:
                raise Fail(f"no saved line: {[e['type'] for e in events]}")
        finally:
            srv.api.practice.stop_all()
            srv.shutdown()
            srv.server_close()
            t.join(5)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        con = sqlite3.connect(str(dbf))
        try:
            word = con.execute("SELECT gloss FROM words WHERE headword = 'paraply'").fetchone()
        finally:
            con.close()
        if word != ("umbrella",):
            raise Fail(f"new word not in the database: {word}")
    return f"{saved[0]}; correction and listening sentence kept out of the chat text"


def main():
    print(f"verify: {os.path.basename(ROOT)}")
    before = snapshot()
    steps = [("compile", step_compile), ("frontmatter", step_frontmatter),
             ("dashboard build", step_dashboard), ("sm2 match", step_sm2_match),
             ("scheduling", step_scheduling), ("readme length", step_readme),
             ("banned strings", step_banned), ("plugin manifest", step_manifest),
             ("unit tests", step_unittests), ("db import", step_db_import),
             ("record round trip", step_record), ("app build", step_app_build),
             ("practice (fake tutor)", step_practice)]
    for name, fn in steps:
        try:
            print(f"{name}: {fn()}")
        except Fail as e:
            reason = " | ".join(x.strip() for x in str(e).splitlines() if x.strip())
            print(f"verify: FAIL at {name}: {reason}")
            return 1
        except Exception as e:                 # a crash in a step is a failure, not a traceback
            print(f"verify: FAIL at {name}: {type(e).__name__}: {e}")
            return 1
    after = snapshot()
    if before != after:
        changed = sorted(set(before) ^ set(after)) or sorted(k for k in before if before[k] != after.get(k))
        print(f"verify: FAIL at unchanged: repository changed: {', '.join(changed[:5])}")
        return 1
    print("unchanged: repository untouched")
    print("verify: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
