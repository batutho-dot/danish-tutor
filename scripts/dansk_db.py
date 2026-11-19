#!/usr/bin/env python3
"""danish-tutor's own store: one SQLite file, an SM-2 scheduler and a small command line.

    python dansk_db.py init
    python dansk_db.py due [--limit N] [--json]
    python dansk_db.py words [--json]
    python dansk_db.py record [--file PAYLOAD.json]     (payload on stdin otherwise)
    python dansk_db.py stats [--json]

Common options: --db PATH (overrides DANISH_TUTOR_DB and the settings file),
--today YYYY-MM-DD (fixed "today", for tests).

Database path, first match wins: --db, the DANISH_TUTOR_DB environment variable, `db_path` in
the settings file (DANISH_TUTOR_CONFIG or ~/.claude/danish-tutor/config.json), and finally
~/.claude/danish-tutor/dansk.db.

Scheduling follows SM-2 as published by P. Wozniak (1990), "SuperMemo 2: Algorithm",
https://super-memory.com/english/ol/sm2.htm. See sm2() for the rules and our reading of them.

All SQL lives in this file, behind small functions, and uses plain types (TEXT, INTEGER,
REAL) and ISO date strings, so a PostgreSQL backend could be added later.

Exit codes for `record`: 0 saved, 1 invalid payload (nothing written), 2 database or I/O error
(transaction rolled back, nothing written).

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dansk_text  # noqa: E402

SCHEMA_VERSION = "1"
EF_START = 2.5
EF_FLOOR = 1.3


# ---------------------------------------------------------------- settings and paths

def config_path() -> Path:
    env = os.environ.get("DANISH_TUTOR_CONFIG")
    return Path(env).expanduser() if env else Path.home() / ".claude" / "danish-tutor" / "config.json"


def load_config() -> dict:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def db_path(cli: str | None = None, cfg: dict | None = None) -> Path:
    if cli:
        return Path(cli).expanduser()
    if os.environ.get("DANISH_TUTOR_DB"):
        return Path(os.environ["DANISH_TUTOR_DB"]).expanduser()
    cfg = load_config() if cfg is None else cfg
    if cfg.get("db_path"):
        return Path(str(cfg["db_path"])).expanduser()
    return Path.home() / ".claude" / "danish-tutor" / "dansk.db"


# ---------------------------------------------------------------- SM-2

def sm2(quality: int, ef: float, interval: int, repetitions: int) -> tuple[float, int, int]:
    """One SM-2 review. Returns (easiness_factor, interval_days, repetitions).

    Rules from Wozniak (1990), https://super-memory.com/english/ol/sm2.htm:
      quality 0..5; a new item starts with EF 2.5;
      I(1) = 1, I(2) = 6, I(n) = I(n-1) * EF for n > 2, fractions rounded up;
      EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), never below 1.3;
      q < 3: start repetitions again from I(1) without changing the EF.

    Our reading where the page leaves room:
      - q >= 3: EF is updated first, then I(n) = ceil(I(n-1) * EF').
      - q < 3: EF kept, repetitions = 0, interval = 1.
      - EF is rounded to 6 decimals so float noise (6 * 2.5 = 15.000000001) cannot push
        ceil() up by a day.
      - The page also re-drills items scoring below 4 the same day. That is a session
        practice, not part of this scheduler.
    """
    if not isinstance(quality, int) or not 0 <= quality <= 5:
        raise ValueError(f"quality must be an integer 0..5, got {quality!r}")
    if quality < 3:
        return ef, 1, 0
    d = 5 - quality
    ef = round(max(EF_FLOOR, ef + (0.1 - d * (0.08 + d * 0.02))), 6)
    repetitions += 1
    if repetitions == 1:
        interval = 1
    elif repetitions == 2:
        interval = 6
    else:
        interval = math.ceil(round(max(interval, 1) * ef, 6))
    return ef, interval, repetitions


def mastery(repetitions: int) -> int:
    """Our own rule, not part of SM-2: mastery level = min(5, repetitions)."""
    return min(5, int(repetitions))


def add_days(iso: str, n: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- schema

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT)""",
    """CREATE TABLE IF NOT EXISTS learner (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        level TEXT,
        target_level TEXT,
        support_language TEXT)""",
    """CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY,
        headword TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        pos TEXT, gender TEXT, level TEXT, forms TEXT,
        definition TEXT, gloss TEXT, notes TEXT,
        learned TEXT, source TEXT)""",
    """CREATE TABLE IF NOT EXISTS examples (
        id INTEGER PRIMARY KEY,
        word_id INTEGER NOT NULL REFERENCES words(id),
        sentence TEXT NOT NULL,
        session_id TEXT)""",
    """CREATE TABLE IF NOT EXISTS items (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        content TEXT, answer TEXT, category TEXT, difficulty TEXT,
        word_id INTEGER REFERENCES words(id),
        easiness_factor REAL NOT NULL,
        interval_days INTEGER NOT NULL,
        repetitions INTEGER NOT NULL,
        due_date TEXT,
        last_reviewed TEXT,
        total_reviews INTEGER NOT NULL,
        mastery_level INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        duration_minutes INTEGER,
        size TEXT, input_mode TEXT, topic TEXT,
        skills TEXT,
        accuracy REAL,
        summary TEXT)""",
    """CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id),
        session_id TEXT,
        date TEXT NOT NULL,
        quality INTEGER NOT NULL,
        ef_after REAL, interval_after INTEGER)""",
    """CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY,
        session_id TEXT,
        pattern_id TEXT NOT NULL,
        category TEXT, said TEXT, correct TEXT, context TEXT, severity TEXT)""",
    """CREATE TABLE IF NOT EXISTS listening (
        id INTEGER PRIMARY KEY,
        session_id TEXT,
        sentence TEXT NOT NULL,
        result TEXT NOT NULL)""",
]


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) and make sure the schema exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        for stmt in SCHEMA:
            con.execute(stmt)
        if get_meta(con, "schema_version") is None:
            set_meta(con, "schema_version", SCHEMA_VERSION)
    return con


def open_existing(path: Path) -> sqlite3.Connection | None:
    """Open only if the file exists (readers must not create an empty database)."""
    return connect(path) if path.is_file() else None


# ---------------------------------------------------------------- small SQL functions

def get_meta(con, key):
    r = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(con, key, value):
    con.execute("DELETE FROM meta WHERE key = ?", (key,))
    con.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


def get_learner(con) -> dict:
    r = con.execute("SELECT level, target_level, support_language FROM learner WHERE id = 1").fetchone()
    return dict(r) if r else {}


def set_learner(con, **fields):
    fields = {k: v for k, v in fields.items() if k in ("level", "target_level", "support_language")}
    if not con.execute("SELECT 1 FROM learner WHERE id = 1").fetchone():
        con.execute("INSERT INTO learner (id) VALUES (1)")
    for k, v in fields.items():
        con.execute(f"UPDATE learner SET {k} = ? WHERE id = 1", (v,))


def find_word(con, headword: str):
    return con.execute("SELECT * FROM words WHERE headword = ?", (headword,)).fetchone()


def insert_word(con, w: dict) -> int:
    cur = con.execute(
        "INSERT INTO words (headword, kind, pos, gender, level, forms, definition, gloss, notes,"
        " learned, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (w["headword"], w.get("kind") or "word", w.get("pos"), w.get("gender"), w.get("level"),
         w.get("forms"), w.get("definition"), w.get("gloss"), w.get("notes"),
         w.get("learned"), w.get("source")))
    return cur.lastrowid


def has_example(con, word_id: int, sentence: str) -> bool:
    return con.execute("SELECT 1 FROM examples WHERE word_id = ? AND sentence = ?",
                       (word_id, sentence)).fetchone() is not None


def insert_example(con, word_id: int, sentence: str, session_id: str | None):
    con.execute("INSERT INTO examples (word_id, sentence, session_id) VALUES (?, ?, ?)",
                (word_id, sentence, session_id))


def get_item(con, item_id: str):
    return con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def item_ids(con) -> set[str]:
    return {r["id"] for r in con.execute("SELECT id FROM items")}


def insert_item(con, it: dict):
    reps = int(it.get("repetitions") or 0)
    con.execute(
        "INSERT INTO items (id, kind, content, answer, category, difficulty, word_id,"
        " easiness_factor, interval_days, repetitions, due_date, last_reviewed, total_reviews,"
        " mastery_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (it["id"], it["kind"], it.get("content"), it.get("answer"), it.get("category"),
         it.get("difficulty"), it.get("word_id"),
         float(it.get("easiness_factor") or EF_START), int(it.get("interval_days") or 0), reps,
         it.get("due_date"), it.get("last_reviewed"), int(it.get("total_reviews") or 0),
         int(it["mastery_level"]) if it.get("mastery_level") is not None else mastery(reps)))


def update_schedule(con, item_id, ef, interval, reps, due, last_reviewed, reviewed: bool):
    con.execute(
        "UPDATE items SET easiness_factor = ?, interval_days = ?, repetitions = ?, due_date = ?,"
        " last_reviewed = COALESCE(?, last_reviewed), total_reviews = total_reviews + ?,"
        " mastery_level = ? WHERE id = ?",
        (ef, interval, reps, due, last_reviewed, 1 if reviewed else 0, mastery(reps), item_id))


def insert_review(con, item_id, session_id, day, quality, ef, interval):
    con.execute("INSERT INTO reviews (item_id, session_id, date, quality, ef_after, interval_after)"
                " VALUES (?, ?, ?, ?, ?, ?)", (item_id, session_id, day, quality, ef, interval))


def session_exists(con, session_id: str) -> bool:
    return con.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None


def insert_session(con, s: dict):
    con.execute(
        "INSERT INTO sessions (id, date, duration_minutes, size, input_mode, topic, skills,"
        " accuracy, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (s["id"], s["date"], s.get("duration_minutes"), s.get("size"), s.get("input_mode"),
         s.get("topic"), json.dumps(s.get("skills") or [], ensure_ascii=False),
         s.get("accuracy"), s.get("summary")))


def insert_error(con, session_id, e: dict):
    con.execute("INSERT INTO errors (session_id, pattern_id, category, said, correct, context,"
                " severity) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, e["pattern_id"], e.get("category"), e.get("said"), e.get("correct"),
                 e.get("context"), e.get("severity")))


def insert_listening(con, session_id, li: dict):
    con.execute("INSERT INTO listening (session_id, sentence, result) VALUES (?, ?, ?)",
                (session_id, li["sentence"], li["result"]))


def all_rows(con, table: str) -> list[dict]:
    if table not in ("words", "examples", "items", "sessions", "reviews", "errors", "listening"):
        raise ValueError(table)
    return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY 1")]


def due_items(con, today: str, limit: int | None = None) -> list[dict]:
    sql = ("SELECT id, kind, content, answer, category, due_date, mastery_level, total_reviews"
           " FROM items WHERE due_date IS NOT NULL AND due_date <= ? ORDER BY due_date, id")
    rows = [dict(r) for r in con.execute(sql, (today,))]
    return rows[:limit] if limit else rows


def count_due(con, day: str) -> int:
    return con.execute("SELECT COUNT(*) FROM items WHERE due_date IS NOT NULL AND due_date <= ?",
                       (day,)).fetchone()[0]


def top_error_patterns(con, limit: int = 5) -> list[dict]:
    rows = con.execute(
        "SELECT e.pattern_id, COUNT(*) AS times, MAX(s.date) AS last_date"
        " FROM errors e LEFT JOIN sessions s ON s.id = e.session_id"
        " GROUP BY e.pattern_id ORDER BY times DESC, last_date DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        last = con.execute("SELECT category, said, correct FROM errors WHERE pattern_id = ?"
                           " ORDER BY id DESC LIMIT 1", (r["pattern_id"],)).fetchone()
        out.append({"pattern_id": r["pattern_id"], "times": r["times"], "last_date": r["last_date"],
                    "category": last["category"], "said": last["said"], "correct": last["correct"]})
    return out


def apply_review(con, item_id: str, quality: int, day: str, session_id: str | None) -> dict:
    """One SM-2 review of one item: schedule updated and a review row logged. Caller owns the
    transaction. Returns the new schedule."""
    it = get_item(con, item_id)
    ef, interval, reps = sm2(quality, it["easiness_factor"], it["interval_days"], it["repetitions"])
    due = add_days(day, interval)
    update_schedule(con, item_id, ef, interval, reps, due, day, True)
    insert_review(con, item_id, session_id, day, quality, ef, interval)
    return {"item_id": item_id, "quality": quality, "easiness_factor": ef, "interval_days": interval,
            "repetitions": reps, "due_date": due, "mastery_level": mastery(reps)}


def preview_review(it, day: str, qualities=range(6)) -> list[dict]:
    """What each quality would do to this item, without writing anything."""
    out = []
    for q in qualities:
        ef, interval, reps = sm2(q, it["easiness_factor"], it["interval_days"], it["repetitions"])
        out.append({"quality": q, "easiness_factor": ef, "interval_days": interval,
                    "repetitions": reps, "due_date": add_days(day, interval)})
    return out


# ---------------------------------------------------------------- reads and edits for the app

WORD_EDIT_FIELDS = ("headword", "forms", "definition", "gloss", "pos", "gender", "level", "notes")
APP_SESSION_PREFIX = "app-review-"


def get_word(con, word_id: int):
    r = con.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    return dict(r) if r else None


def word_examples(con, word_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, sentence, session_id FROM examples WHERE word_id = ? ORDER BY id", (word_id,))]


def items_for_word(con, word_id: int) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM items WHERE word_id = ? ORDER BY id",
                                         (word_id,))]


def item_reviews(con, item_id: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, session_id, date, quality, ef_after, interval_after FROM reviews"
        " WHERE item_id = ? ORDER BY date, id", (item_id,))]


def word_rows(con, today: str, q: str = "", kind: str = "", level: str = "",
              due: str = "") -> list[dict]:
    """The word bank with each word's first linked item. Filters: q (headword or gloss,
    case-insensitive substring), kind (word/grammar), level, due ('due' or 'not_due')."""
    sql = ("SELECT w.id, w.headword, w.kind, w.pos, w.gender, w.level, w.forms, w.gloss,"
           " w.learned, i.id AS item_id, i.mastery_level, i.due_date, i.total_reviews"
           " FROM words w LEFT JOIN items i ON i.id ="
           " (SELECT MIN(i2.id) FROM items i2 WHERE i2.word_id = w.id)")
    where, args = [], []
    if q:
        where.append("(LOWER(w.headword) LIKE ? OR LOWER(COALESCE(w.gloss, '')) LIKE ?)")
        args += [f"%{q.lower()}%", f"%{q.lower()}%"]
    if kind:
        where.append("w.kind = ?")
        args.append(kind)
    if level:
        where.append("w.level = ?")
        args.append(level)
    if due == "due":
        where.append("i.due_date IS NOT NULL AND i.due_date <= ?")
        args.append(today)
    elif due == "not_due":
        where.append("(i.due_date IS NULL OR i.due_date > ?)")
        args.append(today)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY w.headword"
    rows = []
    for r in con.execute(sql, args):
        d = dict(r)
        d["is_due"] = bool(d["due_date"] and d["due_date"] <= today)
        rows.append(d)
    return rows


def word_levels(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT level FROM words WHERE level IS NOT NULL AND level <> '' ORDER BY level")]


def update_word(con, word_id: int, fields: dict) -> None:
    """Change the editable fields of one word. A linked item's content and answer follow the
    headword and gloss, so the review card shows the edited text. Caller owns the transaction."""
    fields = {k: v for k, v in fields.items() if k in WORD_EDIT_FIELDS}
    for k, v in fields.items():
        con.execute(f"UPDATE words SET {k} = ? WHERE id = ?", (v, word_id))
    if "headword" in fields:
        con.execute("UPDATE items SET content = ? WHERE word_id = ?", (fields["headword"], word_id))
    if "gloss" in fields:
        con.execute("UPDATE items SET answer = ? WHERE word_id = ?", (fields["gloss"], word_id))


def delete_word(con, word_id: int) -> dict:
    """Delete a word, its examples, its items and their reviews. Caller owns the transaction."""
    ids = [r["id"] for r in con.execute("SELECT id FROM items WHERE word_id = ?", (word_id,))]
    n_rev = 0
    for iid in ids:
        n_rev += con.execute("DELETE FROM reviews WHERE item_id = ?", (iid,)).rowcount
    n_items = con.execute("DELETE FROM items WHERE word_id = ?", (word_id,)).rowcount
    n_ex = con.execute("DELETE FROM examples WHERE word_id = ?", (word_id,)).rowcount
    n_w = con.execute("DELETE FROM words WHERE id = ?", (word_id,)).rowcount
    return {"words": n_w, "items": n_items, "examples": n_ex, "reviews": n_rev}


def due_cards(con, today: str) -> list[dict]:
    """Every item due on or before today, oldest first, with what a review card shows."""
    rows = con.execute(
        "SELECT i.id AS item_id, i.kind, i.content, i.answer, i.category, i.due_date,"
        " i.mastery_level, i.total_reviews, i.interval_days, i.word_id, w.headword, w.forms,"
        " w.definition, w.gloss, w.pos, w.gender, w.level"
        " FROM items i LEFT JOIN words w ON w.id = i.word_id"
        " WHERE i.due_date IS NOT NULL AND i.due_date <= ? ORDER BY i.due_date, i.id",
        (today,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["examples"] = [e["sentence"] for e in word_examples(con, d["word_id"])] if d["word_id"] else []
        if d["kind"] == "error_pattern":
            pid = d["item_id"][len("error_"):] if d["item_id"].startswith("error_") else d["item_id"]
            e = con.execute("SELECT context, severity FROM errors WHERE pattern_id IN (?, ?)"
                            " ORDER BY id DESC LIMIT 1", (pid, d["item_id"])).fetchone()
            d["context"] = e["context"] if e else None
            d["severity"] = e["severity"] if e else None
        out.append(d)
    return out


def error_pattern_items(con, today: str | None = None) -> list[dict]:
    """Error-pattern items (what was said, the correct form), oldest due first; only those
    due on or before `today` when it is given."""
    sql = ("SELECT id, content, answer, category, due_date, total_reviews, mastery_level"
           " FROM items WHERE kind = 'error_pattern'")
    args = []
    if today:
        sql += " AND due_date IS NOT NULL AND due_date <= ?"
        args.append(today)
    sql += " ORDER BY due_date, id"
    return [dict(r) for r in con.execute(sql, args)]


def session_rows(con) -> list[dict]:
    rows = con.execute(
        "SELECT s.id, s.date, s.duration_minutes, s.size, s.input_mode, s.topic, s.skills,"
        " s.accuracy, s.summary,"
        " (SELECT COUNT(*) FROM errors e WHERE e.session_id = s.id) AS errors,"
        " (SELECT COUNT(*) FROM reviews r WHERE r.session_id = s.id) AS reviews,"
        " (SELECT COUNT(*) FROM listening l WHERE l.session_id = s.id) AS listening"
        " FROM sessions s ORDER BY s.date DESC, s.id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["skills"] = _skills(d["skills"])
        out.append(d)
    return out


def _skills(text) -> list[str]:
    try:
        v = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def get_session(con, session_id: str):
    r = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["skills"] = _skills(d["skills"])
    d["errors"] = [dict(e) for e in con.execute(
        "SELECT pattern_id, category, said, correct, context, severity FROM errors"
        " WHERE session_id = ? ORDER BY id", (session_id,))]
    d["listening"] = [dict(li) for li in con.execute(
        "SELECT sentence, result FROM listening WHERE session_id = ? ORDER BY id", (session_id,))]
    d["reviews"] = [dict(x) for x in con.execute(
        "SELECT r.item_id, r.quality, r.interval_after, i.content FROM reviews r"
        " LEFT JOIN items i ON i.id = r.item_id WHERE r.session_id = ? ORDER BY r.id",
        (session_id,))]
    return d


def minutes_by_day(con, first: str, last: str) -> dict[str, int]:
    return {r[0]: int(r[1] or 0) for r in con.execute(
        "SELECT date, SUM(COALESCE(duration_minutes, 0)) FROM sessions"
        " WHERE date >= ? AND date <= ? GROUP BY date", (first, last))}


def reviews_by_day(con, first: str, last: str) -> dict[str, int]:
    return {r[0]: int(r[1]) for r in con.execute(
        "SELECT date, COUNT(*) FROM reviews WHERE date >= ? AND date <= ? GROUP BY date",
        (first, last))}


def session_dates(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT DISTINCT date FROM sessions ORDER BY date")]


def ensure_app_session(con, day: str, seconds: int) -> str:
    """The session row that reviews done in the app belong to: one per day, id
    app-review-YYYY-MM-DD, input_mode typed, size small, skills ["vocabulary"]. Its
    duration_minutes is the time spent on the cards that day, rounded to whole minutes; the
    exact seconds are kept in meta. Caller owns the transaction."""
    sid = APP_SESSION_PREFIX + day
    key = "app_review_seconds:" + sid
    total = int(get_meta(con, key) or 0) + max(0, int(seconds))
    set_meta(con, key, total)
    minutes = round(total / 60)
    if session_exists(con, sid):
        con.execute("UPDATE sessions SET duration_minutes = ? WHERE id = ?", (minutes, sid))
    else:
        insert_session(con, {"id": sid, "date": day, "duration_minutes": minutes, "size": "small",
                             "input_mode": "typed", "topic": "Review in the app",
                             "skills": ["vocabulary"], "accuracy": None,
                             "summary": "Flash-card review done in the local app."})
    return sid


def headwords(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT headword, kind, gloss FROM words ORDER BY headword")]


def counts(con) -> dict:
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "words": one("SELECT COUNT(*) FROM words WHERE kind = 'word'"),
        "grammar": one("SELECT COUNT(*) FROM words WHERE kind = 'grammar'"),
        "items": one("SELECT COUNT(*) FROM items"),
        "sessions": one("SELECT COUNT(*) FROM sessions"),
        "reviews": one("SELECT COUNT(*) FROM reviews"),
        "errors": one("SELECT COUNT(*) FROM errors"),
        "listening": one("SELECT COUNT(*) FROM listening"),
    }


# ---------------------------------------------------------------- payload validation

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PATTERN_ID = re.compile(r"^[a-z0-9_]+$")
TOP_KEYS = {"date", "duration_minutes", "size", "input_mode", "topic", "summary", "skills",
            "accuracy", "reviews", "errors", "new_words", "listening"}
REVIEW_KEYS = {"item_id", "quality"}
ERROR_KEYS = {"pattern_id", "category", "said", "correct", "context", "severity"}
WORD_KEYS = {"headword", "kind", "pos", "gender", "level", "forms", "definition", "gloss",
             "example", "category", "notes"}
LISTEN_KEYS = {"sentence", "result"}
SIZES = {"small", "large"}
INPUT_MODES = {"voice", "typed", "mixed"}
SEVERITIES = {"critical", "moderate", "minor"}
RESULTS = {"understood_fully", "gist_only", "missed"}


def is_date(s) -> bool:
    if not isinstance(s, str) or not ISO.match(s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def validate(p, known_items: set[str]) -> list[str]:
    """Every problem in the payload, as short lines. Empty list means valid."""
    if not isinstance(p, dict):
        return ["payload must be a JSON object"]
    errs = []
    for k in sorted(set(p) - TOP_KEYS):
        errs.append(f"unknown key: {k}")
    if not is_date(p.get("date")):
        errs.append("date: must be YYYY-MM-DD")
    dm = p.get("duration_minutes")
    if not isinstance(dm, int) or isinstance(dm, bool) or dm < 0:
        errs.append("duration_minutes: must be a whole number >= 0")
    if p.get("size") not in SIZES:
        errs.append("size: must be small or large")
    if p.get("input_mode") not in INPUT_MODES:
        errs.append("input_mode: must be voice, typed or mixed")
    for k in ("topic", "summary"):
        if not isinstance(p.get(k, ""), str):
            errs.append(f"{k}: must be text")
    sk = p.get("skills", [])
    if not isinstance(sk, list) or not all(isinstance(x, str) and x for x in sk):
        errs.append("skills: must be a list of text")
    acc = p.get("accuracy")
    if acc is not None and (isinstance(acc, bool) or not isinstance(acc, (int, float))
                            or not 0 <= acc <= 1):
        errs.append("accuracy: must be a number from 0 to 1")

    def entries(key, allowed):
        v = p.get(key, [])
        if not isinstance(v, list):
            errs.append(f"{key}: must be a list")
            return []
        out = []
        for i, e in enumerate(v):
            if not isinstance(e, dict):
                errs.append(f"{key}[{i}]: must be an object")
                continue
            for k in sorted(set(e) - allowed):
                errs.append(f"{key}[{i}]: unknown key {k}")
            out.append((i, e))
        return out

    for i, r in entries("reviews", REVIEW_KEYS):
        q = r.get("quality")
        if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= 5:
            errs.append(f"reviews[{i}].quality: must be a whole number 0 to 5")
        if r.get("item_id") not in known_items:
            errs.append(f"reviews[{i}].item_id: no item {r.get('item_id')!r} in the database")
    for i, e in entries("errors", ERROR_KEYS):
        if not isinstance(e.get("pattern_id"), str) or not PATTERN_ID.match(e["pattern_id"]):
            errs.append(f"errors[{i}].pattern_id: lower-case letters, digits and _ only")
        for k in ("said", "correct"):
            if not isinstance(e.get(k), str) or not e[k].strip():
                errs.append(f"errors[{i}].{k}: required text")
        for k in ("category", "context"):
            if not isinstance(e.get(k, ""), str):
                errs.append(f"errors[{i}].{k}: must be text")
        if e.get("severity", "moderate") not in SEVERITIES:
            errs.append(f"errors[{i}].severity: must be critical, moderate or minor")
    for i, w in entries("new_words", WORD_KEYS):
        if not isinstance(w.get("headword"), str) or not w["headword"].strip():
            errs.append(f"new_words[{i}].headword: required text")
        elif not dansk_text.item_key(w["headword"]):
            errs.append(f"new_words[{i}].headword: gives an empty id")
        if w.get("kind", "word") not in ("word", "grammar"):
            errs.append(f"new_words[{i}].kind: must be word or grammar")
        for k in WORD_KEYS - {"headword", "kind"}:
            if w.get(k) is not None and not isinstance(w[k], str):
                errs.append(f"new_words[{i}].{k}: must be text")
    for i, li in entries("listening", LISTEN_KEYS):
        if not isinstance(li.get("sentence"), str) or not li["sentence"].strip():
            errs.append(f"listening[{i}].sentence: required text")
        if li.get("result") not in RESULTS:
            errs.append(f"listening[{i}].result: must be understood_fully, gist_only or missed")
    return errs


# ---------------------------------------------------------------- record

def next_session_id(con, day: str) -> str:
    base = f"session-{day}"
    if not session_exists(con, base):
        return base
    n = 2
    while session_exists(con, f"{base}-{n}"):
        n += 1
    return f"{base}-{n}"


def word_item_id(headword: str, kind: str) -> str:
    return ("grammar_" if kind == "grammar" else "vocab_") + dansk_text.item_key(headword)


def error_item_id(pattern_id: str) -> str:
    return pattern_id if pattern_id.startswith("error_") else "error_" + pattern_id


def apply_record(con, p: dict, cfg: dict) -> dict:
    """Write one validated payload. Caller owns the transaction."""
    day = p["date"]
    tomorrow = add_days(day, 1)
    sid = next_session_id(con, day)
    note_name = dansk_text.session_note_name(sid)
    insert_session(con, {"id": sid, "date": day, "duration_minutes": p["duration_minutes"],
                         "size": p["size"], "input_mode": p["input_mode"],
                         "topic": p.get("topic", ""), "skills": p.get("skills", []),
                         "accuracy": p.get("accuracy"), "summary": p.get("summary", "")})
    learner = {k: cfg[k] for k in ("level", "target_level", "support_language") if cfg.get(k)}
    if learner or not get_learner(con):
        set_learner(con, **{"level": "A2", "target_level": "B2", "support_language": "English",
                            **get_learner(con), **learner})

    for r in p.get("reviews", []):
        apply_review(con, r["item_id"], r["quality"], day, sid)

    new_count = 0
    note_jobs = []
    for w in p.get("new_words", []):
        kind = w.get("kind") or "word"
        head = w["headword"].strip()
        row = find_word(con, head)
        if row is None:
            wid = insert_word(con, {**w, "headword": head, "kind": kind, "learned": day,
                                    "source": note_name})
            iid = word_item_id(head, kind)
            if get_item(con, iid) is None:
                insert_item(con, {"id": iid, "kind": "grammar" if kind == "grammar" else "vocabulary",
                                  "content": head, "answer": w.get("gloss"),
                                  "category": w.get("category"), "difficulty": w.get("level"),
                                  "word_id": wid, "due_date": tomorrow})
            new_count += 1
            note_jobs.append(("new", {**w, "headword": head, "kind": kind}))
        else:
            wid = row["id"]
            note_jobs.append(("old", {**w, "headword": head}))
        if w.get("example") and not has_example(con, wid, w["example"]):
            insert_example(con, wid, w["example"], sid)

    for e in p.get("errors", []):
        e = {"severity": "moderate", **e}
        insert_error(con, sid, e)
        iid = error_item_id(e["pattern_id"])
        it = get_item(con, iid)
        if it is None:
            insert_item(con, {"id": iid, "kind": "error_pattern", "content": e["said"],
                              "answer": e["correct"], "category": e.get("category"),
                              "due_date": tomorrow})
        else:
            update_schedule(con, iid, it["easiness_factor"], 1, 0, tomorrow, None, False)

    for li in p.get("listening", []):
        insert_listening(con, sid, li)

    return {"session_id": sid, "note_name": note_name, "reviews": len(p.get("reviews", [])),
            "new_words": new_count, "errors": len(p.get("errors", [])),
            "due_tomorrow": count_due(con, tomorrow), "note_jobs": note_jobs}


def write_notes(notes_dir: Path, p: dict, result: dict) -> list[Path]:
    """Markdown word notes and a session record, in the format the dashboard reads."""
    words_dir, sessions_dir = notes_dir / "words", notes_dir / "sessions"
    words_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    written = []
    name = result["note_name"]
    for state, w in result["note_jobs"]:
        f = words_dir / dansk_text.note_filename(w["headword"])
        if f.exists():
            if w.get("example"):
                text = f.read_text(encoding="utf-8")
                if w["example"] not in text:
                    f.write_text(dansk_text.add_example(text, w["example"], name), encoding="utf-8")
                    written.append(f)
        else:
            f.write_text(dansk_text.word_note(w, p["date"], name), encoding="utf-8")
            written.append(f)
    s = sessions_dir / f"{name}.md"
    s.write_text(dansk_text.session_note(p, name), encoding="utf-8")
    written.append(s)
    return written


# ---------------------------------------------------------------- command line

def _today(a) -> str:
    if a.today:
        if not is_date(a.today):
            raise SystemExit("--today must be YYYY-MM-DD")
        return a.today
    return date.today().isoformat()


def cmd_init(a, cfg) -> int:
    path = db_path(a.db, cfg)
    con = connect(path)
    if not get_learner(con):
        with con:
            set_learner(con, level=cfg.get("level") or "A2",
                        target_level=cfg.get("target_level") or "B2",
                        support_language=cfg.get("support_language") or "English")
    con.close()
    print(f"database ready: {path}")
    return 0


def cmd_due(a, cfg) -> int:
    path = db_path(a.db, cfg)
    today = _today(a)
    con = open_existing(path)
    if con is None:
        out = {"today": today, "first_session": True, "due_count": 0, "due_items": [],
               "error_patterns": [], "learner": {}, "database": str(path)}
    else:
        out = {"today": today, "first_session": counts(con)["sessions"] == 0,
               "due_count": count_due(con, today),
               "due_items": due_items(con, today, a.limit),
               "error_patterns": top_error_patterns(con), "learner": get_learner(con),
               "database": str(path)}
        con.close()
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if out["first_session"]:
        print("no sessions recorded yet: this is the first session")
    shown = f" (showing {len(out['due_items'])})" if len(out["due_items"]) < out["due_count"] else ""
    print(f"{out['due_count']} items due on {today}{shown}")
    for it in out["due_items"]:
        print(f"  {it['due_date']}  {it['id']}: {it['content']} = {it['answer']}")
    for e in out["error_patterns"]:
        print(f"  error {e['pattern_id']} x{e['times']}: {e['said']} -> {e['correct']}")
    return 0


def cmd_words(a, cfg) -> int:
    con = open_existing(db_path(a.db, cfg))
    rows = headwords(con) if con else []
    if con:
        con.close()
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"{len(rows)} headwords")
        for r in rows:
            print(f"  {r['headword']} ({r['kind']}): {r['gloss'] or ''}")
    return 0


def cmd_stats(a, cfg) -> int:
    path = db_path(a.db, cfg)
    today = _today(a)
    con = open_existing(path)
    c = counts(con) if con else dict.fromkeys(
        ("words", "grammar", "items", "sessions", "reviews", "errors", "listening"), 0)
    c["due_today"] = count_due(con, today) if con else 0
    c["today"] = today
    c["database"] = str(path)
    if con:
        con.close()
    if a.json:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(f"{path}")
        print(f"  {c['words']} words, {c['grammar']} grammar notes, {c['items']} items "
              f"({c['due_today']} due on {today}), {c['sessions']} sessions, "
              f"{c['reviews']} reviews, {c['errors']} errors")
    return 0


def cmd_record(a, cfg) -> int:
    try:
        raw = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
    except OSError as e:
        print(f"not saved: cannot read payload: {e}")
        return 1
    try:
        p = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"not saved: payload is not valid JSON: {e}")
        return 1
    path = db_path(a.db, cfg)
    try:
        con = connect(path)
    except (sqlite3.Error, OSError) as e:
        print(f"not saved: cannot open database {path}: {e}")
        return 2
    try:
        errs = validate(p, item_ids(con))
        if errs:
            print("not saved: invalid payload")
            for e in errs:
                print(f"  {e}")
            return 1
        try:
            with con:                       # one transaction: commit on success, else roll back
                result = apply_record(con, p, cfg)
        except (sqlite3.Error, OSError, ValueError) as e:
            print(f"not saved: database error, nothing written: {e}")
            return 2
    finally:
        con.close()

    print(f"saved {result['session_id']}, {result['reviews']} reviews, "
          f"{result['new_words']} new words, {result['errors']} errors; "
          f"{result['due_tomorrow']} items due tomorrow")
    notes = str(cfg.get("notes_dir") or "").strip()
    if notes:
        try:
            files = write_notes(Path(notes).expanduser(), p, result)
            print(f"notes: {len(files)} files written under {Path(notes).expanduser()}")
        except OSError as e:
            print(f"warning: database saved, but notes not written: {e}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="database file (overrides DANISH_TUTOR_DB and db_path)")
    common.add_argument("--today", help="treat this YYYY-MM-DD as today")
    common.add_argument("--json", action="store_true", help="print JSON")
    ap = argparse.ArgumentParser(description="danish-tutor database and SM-2 scheduler")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", parents=[common], help="create the database")
    d = sub.add_parser("due", parents=[common], help="items due and top error patterns")
    d.add_argument("--limit", type=int, help="at most N items")
    sub.add_parser("words", parents=[common], help="known headwords")
    r = sub.add_parser("record", parents=[common], help="save one session (JSON payload)")
    r.add_argument("--file", help="read the payload from this file instead of stdin")
    sub.add_parser("stats", parents=[common], help="counts")
    a = ap.parse_args(argv)
    cfg = load_config()
    return {"init": cmd_init, "due": cmd_due, "words": cmd_words, "record": cmd_record,
            "stats": cmd_stats}[a.cmd](a, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
