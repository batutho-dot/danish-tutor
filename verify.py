#!/usr/bin/env python3
"""verify.py: check danish-tutor end to end and print PASS or FAIL from real runs.

    python verify.py

Steps: every .py compiles; the skill has frontmatter whose name matches its folder and a
description; the dashboard builds from example-data into a temporary folder and the page
holds a fixed string from the example data; word notes are matched to their spaced-repetition
items with the expected due dates; the README is at most 550 words; no file holds a banned
string or an audio file; the repository is unchanged afterwards.

The SM-2 interval arithmetic is not tested here: it lives in the external Fluent plugin's
update-db.py, which this repository does not contain. The step says so and is skipped.

Needs only the Python standard library. Writes nothing inside the repository.
"""
import importlib.util
import os
import re
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
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", ".venv", "data")]
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
    for d in sorted(os.listdir(os.path.join(ROOT, "skill"))):
        p = os.path.join(ROOT, "skill", d, "SKILL.md")
        if os.path.isfile(p):
            skills.append((d, p))
    if not skills:
        raise Fail("no skill/*/SKILL.md found")
    for folder, p in skills:
        text = open(p, encoding="utf-8").read()
        m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
        if not m:
            raise Fail(f"skill/{folder}/SKILL.md: no frontmatter")
        name = re.search(r"^name:\s*(\S+)", m.group(1), re.M)
        if not name or name.group(1) != folder:
            raise Fail(f"skill/{folder}/SKILL.md: name does not match folder")
        if not re.search(r"^description:\s*\S", m.group(1), re.M):
            raise Fail(f"skill/{folder}/SKILL.md: no description")
    return f"{len(skills)} skill(s)"


def step_dashboard():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "dash.html")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        env.pop("DANSK_DATA_DIR", None)
        env.pop("DANSK_WORDS_DIR", None)
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
    return ("skipped: SM-2 intervals are computed by the external Fluent plugin's "
            "update-db.py, which is not in this repository")


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
        for n, line in enumerate(text.splitlines(), 1):
            if rel == "LICENSE" and line.startswith("Copyright (c)"):
                continue                       # the licence holder's line stays as written
            for rx, what in BANNED:
                if rx.search(line):
                    hits.append(f"{rel}:{n} {what}")
    if hits:
        raise Fail("; ".join(hits[:8]) + (f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""))
    return "none"


def main():
    print(f"verify: {os.path.basename(ROOT)}")
    before = snapshot()
    steps = [("compile", step_compile), ("frontmatter", step_frontmatter),
             ("dashboard build", step_dashboard), ("sm2 match", step_sm2_match),
             ("scheduling", step_scheduling), ("readme length", step_readme),
             ("banned strings", step_banned)]
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
