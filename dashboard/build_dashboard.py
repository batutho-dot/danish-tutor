#!/usr/bin/env python3
"""Build a static Danish practice dashboard from the danish-tutor database, or from
Fluent-format JSON files and a folder of word notes.

Database mode (the default):
  python dashboard/build_dashboard.py                 the configured database
  python dashboard/build_dashboard.py --db dansk.db   a given database file
The database path follows scripts/dansk_db.py: --db, DANISH_TUTOR_DB, `db_path` in the
settings file, then ~/.claude/danish-tutor/dansk.db.

JSON mode (--data DIR, or the DANSK_DATA_DIR environment variable):
  <data>/spaced-repetition.json   SM-2 items and the review queue
  <data>/learner-profile.json     level, target level, streak, practice minutes
  <data>/progress-db.json         overall session count and accuracy
  <data>/session-log.json         one entry per session
  <words>/*.md                    one note per word or grammar rule (default <data>/words,
                                  or DANSK_WORDS_DIR)
  python dashboard/build_dashboard.py --data example-data

Writes one self-contained HTML file (default: dansk-dashboard.html in the system temp folder).
Nothing is sent anywhere: the page is built locally and opened from disk.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "dashboard.template.html"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Folding, note parsing and the item-id rules live in scripts/dansk_text.py, shared with the
# database script and the importer. fold and read_words stay importable from here.
from dansk_text import ARTICLE, fold, read_words, section, split_frontmatter  # noqa: E402,F401


def load_json(folder: Path, name: str) -> dict:
    p = folder / name
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def attach_sm2(words: list[dict], sr: dict, today: date) -> None:
    """Match each note to its SM-2 item so the page can show mastery and due date."""
    items = sr.get("items", {}) or {}
    index: dict[str, dict] = {}
    for iid, item in items.items():
        index[fold(iid)] = item
        index[fold(iid.replace("vocab_", "").replace("grammar_", ""))] = item
        for part in re.split(r"[/,]", str(item.get("content", ""))):
            part = part.strip()
            if part:
                index[fold(part)] = item
                index[fold(ARTICLE.sub("", part))] = item

    iso = today.isoformat()
    for w in words:
        item = index.get(fold(ARTICLE.sub("", w["head"]))) or index.get(fold(w["head"]))
        if not item:
            w.update(mastery=0, due=None, reviews=0, overdue=False, ef=None)
            continue
        due = item.get("due_date")
        w.update(
            mastery=int(item.get("mastery_level") or 0),
            due=due,
            reviews=int(item.get("total_reviews") or 0),
            overdue=bool(due and due <= iso),
            ef=item.get("easiness_factor"),
        )


def session_minutes(s: dict) -> int:
    return int(s.get("duration_minutes") or s.get("duration") or 0)


def session_day(s: dict) -> date | None:
    try:
        return datetime.fromisoformat(str(s.get("date"))[:10]).date()
    except (ValueError, TypeError):
        return None


def build_stats(words, sr, progress, profile, sessions, today: date) -> dict:
    items = list((sr.get("items", {}) or {}).values())
    iso = today.isoformat()
    log = sessions.get("sessions", []) or []

    week_start = today - timedelta(days=today.weekday())
    by_day: dict[str, int] = {}
    minutes_week = 0
    last = None
    for s in log:
        d = session_day(s)
        if d is None:
            continue
        by_day[d.isoformat()] = by_day.get(d.isoformat(), 0) + session_minutes(s)
        if d >= week_start:
            minutes_week += session_minutes(s)
        if last is None or d > last:
            last = d

    learner = profile.get("learner") or {}
    skills = profile.get("skills") or {}
    overall = progress.get("overall_stats") or {}
    return {
        "today": iso,
        "words": sum(1 for w in words if w["kind"] == "word"),
        "grammar": sum(1 for w in words if w["kind"] == "grammar"),
        "due": sum(1 for i in items if (i.get("due_date") or "9999") <= iso),
        "tracked": len(items),
        "streak": int(profile.get("current_streak_days") or 0),
        "minutes_week": minutes_week,
        "sessions": int(overall.get("total_sessions") or 0),
        "accuracy": overall.get("accuracy_rate"),
        "level": learner.get("current_level") or "",
        "target": learner.get("target_level") or "",
        "days": [{"date": (today - timedelta(days=n)).isoformat(),
                  "min": by_day.get((today - timedelta(days=n)).isoformat(), 0)}
                 for n in range(13, -1, -1)],
        "last_session": last.isoformat() if last else None,
        "gap_days": (today - last).days if last else None,
        "speaking": int((skills.get("speaking") or {}).get("total_practice_time") or 0),
        "listening": int((skills.get("listening") or {}).get("total_practice_time") or 0),
        "example_data": bool(sr.get("_note") or profile.get("_note")),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def build_patterns(sr: dict, today: date) -> list[dict]:
    """Error patterns due for review, oldest first."""
    iso = today.isoformat()
    due = [i for i in (sr.get("items", {}) or {}).values()
           if i.get("type") == "error_pattern" and (i.get("due_date") or "9999") <= iso]
    due.sort(key=lambda i: i.get("due_date") or "")
    return [{"wrong": i.get("content"), "right": i.get("answer"), "cat": i.get("category"),
             "due": i.get("due_date")} for i in due[:6]]


def build_sessions(sessions: dict) -> list[dict]:
    rows = []
    for s in sessions.get("sessions", []) or []:
        rows.append({
            "id": s.get("session_id") or s.get("id") or "",
            "date": str(s.get("date"))[:10],
            "min": session_minutes(s),
            "size": s.get("size") or "",
            "skills": s.get("skills_practiced") or s.get("skills") or [],
            "acc": s.get("accuracy"),
            "notes": s.get("notes") or s.get("summary") or "",
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:12]


def build_data(data_dir: Path, words_dir: Path, today: date) -> dict:
    sr = load_json(data_dir, "spaced-repetition.json")
    profile = load_json(data_dir, "learner-profile.json")
    sessions = load_json(data_dir, "session-log.json")
    words = read_words(words_dir)
    attach_sm2(words, sr, today)
    return {
        "words": words,
        "stats": build_stats(words, sr, load_json(data_dir, "progress-db.json"),
                             profile, sessions, today),
        "patterns": build_patterns(sr, today),
        "sessions": build_sessions(sessions),
    }


def db_records(db_file: Path) -> tuple[list[dict], dict, dict, dict, dict]:
    """Read the database into the same shapes the JSON mode reads:
    (words, spaced-repetition, progress, learner profile, session log)."""
    import dansk_db

    con = dansk_db.connect(db_file)
    try:
        learner = dansk_db.get_learner(con)
        example = dansk_db.get_meta(con, "example_data") == "true"
        rows = dansk_db.all_rows(con, "words")
        examples: dict[int, list[str]] = {}
        for e in dansk_db.all_rows(con, "examples"):
            examples.setdefault(e["word_id"], []).append(e["sentence"])
        items = dansk_db.all_rows(con, "items")
        sessions = dansk_db.all_rows(con, "sessions")
    finally:
        con.close()

    words = [{
        "kind": w["kind"], "file": "", "head": w["headword"], "forms": w["forms"] or "",
        "da": w["definition"] or "", "gloss": w["gloss"] or "",
        "ex": examples.get(w["id"], [])[:3], "pos": w["pos"] or "", "gender": w["gender"] or "",
        "level": w["level"] or "", "learned": w["learned"] or "", "example_data": example,
    } for w in rows]
    sr = {"items": {i["id"]: {
        "id": i["id"], "type": i["kind"], "content": i["content"], "answer": i["answer"],
        "category": i["category"], "due_date": i["due_date"], "mastery_level": i["mastery_level"],
        "total_reviews": i["total_reviews"], "easiness_factor": i["easiness_factor"],
    } for i in items}}
    log = {"sessions": [{
        "session_id": s["id"], "date": s["date"], "duration_minutes": s["duration_minutes"],
        "size": s["size"], "skills_practiced": json.loads(s["skills"] or "[]"),
        "accuracy": s["accuracy"], "notes": s["summary"] or s["topic"] or "",
    } for s in sessions]}
    accs = [s["accuracy"] for s in sessions if s["accuracy"] is not None]
    progress = {"overall_stats": {
        "total_sessions": len(sessions),
        "accuracy_rate": round(sum(accs) / len(accs), 2) if accs else None}}

    def skill_minutes(skill: str) -> int:
        return sum(int(s["duration_minutes"] or 0) for s in log["sessions"]
                   if skill in s["skills_practiced"])

    profile = {
        "learner": {"current_level": learner.get("level"),
                    "target_level": learner.get("target_level"),
                    "native_language": learner.get("support_language")},
        "current_streak_days": streak(sorted({s["date"] for s in sessions})),
        "skills": {"speaking": {"total_practice_time": skill_minutes("speaking")},
                   "listening": {"total_practice_time": skill_minutes("listening")}},
    }
    if example:
        sr["_note"] = profile["_note"] = "Invented example data."
    return words, sr, progress, profile, log


def streak(days: list[str]) -> int:
    """Consecutive days with a session, counted back from the latest one."""
    if not days:
        return 0
    n, cur = 1, date.fromisoformat(days[-1])
    for d in reversed(days[:-1]):
        if date.fromisoformat(d) == cur - timedelta(days=1):
            n, cur = n + 1, cur - timedelta(days=1)
        else:
            break
    return n


def build_data_db(db_file: Path, today: date) -> dict:
    """Database mode: the same dict build_data() returns, built from the SQLite file."""
    words, sr, progress, profile, sessions = db_records(db_file)
    attach_sm2(words, sr, today)
    return {
        "words": words,
        "stats": build_stats(words, sr, progress, profile, sessions, today),
        "patterns": build_patterns(sr, today),
        "sessions": build_sessions(sessions),
    }


def write_page(data: dict, out: Path) -> None:
    blob = json.dumps(data, ensure_ascii=False)
    # A word note could hold "</script>"; escape the slash so it cannot close the tag.
    blob = blob.replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


def build_page(data_dir: Path, words_dir: Path, out: Path, today: date) -> dict:
    data = build_data(data_dir, words_dir, today)
    write_page(data, out)
    return data


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", help="database file (default: the configured database)")
    ap.add_argument("--data", help="JSON mode: folder with the JSON files (or DANSK_DATA_DIR)")
    ap.add_argument("--words", help="JSON mode: folder with the word notes "
                                    "(or DANSK_WORDS_DIR; default <data>/words)")
    ap.add_argument("--out", help="HTML file to write (default: system temp folder)")
    ap.add_argument("--today", help="treat this YYYY-MM-DD as today (for tests)")
    a = ap.parse_args(argv)

    if a.db and a.data:
        print("pass either --db or --data, not both")
        return 1
    out = Path(a.out).expanduser() if a.out else Path(tempfile.gettempdir()) / "dansk-dashboard.html"
    today = date.fromisoformat(a.today) if a.today else date.today()
    data_arg = None if a.db else (a.data or os.environ.get("DANSK_DATA_DIR"))

    if data_arg:
        data_dir = Path(data_arg).expanduser()
        source = Path(a.words or os.environ.get("DANSK_WORDS_DIR") or data_dir / "words").expanduser()
        if not data_dir.is_dir():
            print(f"no data folder at {data_dir}: pass --data or set DANSK_DATA_DIR")
            return 1
        data = build_page(data_dir, source, out, today)
    else:
        import dansk_db
        source = dansk_db.db_path(a.db)
        if not source.is_file():
            print(f"no database at {source}: run a session first, import with "
                  f"scripts/import_fluent.py, or pass --data for JSON mode")
            return 1
        data = build_data_db(source, today)
        write_page(data, out)

    s = data["stats"]
    print(f"wrote {out}")
    print(f"  {s['words']} word notes, {s['grammar']} grammar notes, "
          f"{s['tracked']} tracked items, {s['due']} due on {s['today']}")
    if not data["words"]:
        print(f"  warning: no word notes found in {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
