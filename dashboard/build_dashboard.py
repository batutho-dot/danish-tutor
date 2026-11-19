#!/usr/bin/env python3
"""Build a static Danish practice dashboard from a word bank and the spaced-repetition files.

Reads, from one data folder:
  <data>/spaced-repetition.json   SM-2 items and the review queue
  <data>/learner-profile.json     level, target level, streak, practice minutes
  <data>/progress-db.json         overall session count and accuracy
  <data>/session-log.json         one entry per session
  <words>/*.md                    one note per word or grammar rule (default <data>/words)

Writes one self-contained HTML file (default: dansk-dashboard.html in the system temp folder).

Usage:
  python dashboard/build_dashboard.py --data example-data
  python dashboard/build_dashboard.py --data ~/.claude/fluent-data --words ~/danish-tutor/data/words --out dash.html

The data folder can also come from the DANSK_DATA_DIR environment variable, and the word
folder from DANSK_WORDS_DIR. Nothing is sent anywhere: the page is built locally and opened
from disk.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "dashboard.template.html"
DEFAULT_DATA = Path.home() / ".claude" / "fluent-data"

# Item ids in the spaced-repetition file are written without Danish letters
# (vocab_noegle for noegle), so both sides are folded the same way before matching.
FOLD = str.maketrans({"æ": "ae", "ø": "oe", "å": "aa", "Æ": "ae", "Ø": "oe", "Å": "aa"})
ARTICLE = re.compile(r"^(at|en|et)\s+")


def fold(s: str) -> str:
    return s.translate(FOLD).lower().replace(" ", "_").replace("-", "_")


def load_json(folder: Path, name: str) -> dict:
    p = folder / name
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the leading --- block. Flat scalars and [a, b] lists only, which is all the
    word notes use. Returns ({}, text) when there is no frontmatter."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw, body = text[3:end], text[end + 4:]
    meta: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            v = val.strip("'\"")
            meta[key] = None if v in ("null", "~", "") else v
    return meta, body


def section(body: str, *headings: str) -> str:
    """Text under the first '## <heading>' found, up to the next heading."""
    for heading in headings:
        m = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.M)
        if not m:
            continue
        rest = body[m.end():]
        nxt = re.search(r"^##\s+", rest, re.M)
        return (rest[:nxt.start()] if nxt else rest).strip()
    return ""


def read_words(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("*.md")):
        if p.stem.lower() in ("index", "readme"):
            continue
        meta, body = split_frontmatter(p.read_text(encoding="utf-8"))
        kind = (meta.get("type") or "").strip()
        if kind not in ("word", "grammar"):
            continue

        h = re.search(r"^#\s+(.+)$", body, re.M)
        headword = h.group(1).strip() if h else (meta.get("title") or p.stem)

        # The bold line straight after the heading holds the inflection forms.
        forms = ""
        if h:
            b = re.match(r"\*\*(.+?)\*\*", body[h.end():].lstrip("\n"))
            if b:
                forms = b.group(1).strip()

        examples = [
            re.sub(r"\(\[\[.*?\]\]\)", "", ln).strip(" -*\t").strip()
            for ln in section(body, "Eksempler").splitlines()
            if ln.strip().startswith(("-", "*"))
        ]
        out.append({
            "kind": kind,
            "file": p.name,
            "head": headword,
            "forms": forms,
            "da": " ".join(section(body, "På dansk", "Reglen").split()),
            "gloss": " ".join(section(body, "Gloss").split()),
            "ex": [e for e in examples if e][:3],
            "pos": meta.get("pos") or "",
            "gender": meta.get("gender") or "",
            "level": meta.get("level") or "",
            "learned": meta.get("learned") or "",
            "example_data": str(meta.get("example_data") or "").lower() == "true",
        })
    return out


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


def build_page(data_dir: Path, words_dir: Path, out: Path, today: date) -> dict:
    data = build_data(data_dir, words_dir, today)
    blob = json.dumps(data, ensure_ascii=False)
    # A word note could hold "</script>"; escape the slash so it cannot close the tag.
    blob = blob.replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", help="folder with the JSON files (or DANSK_DATA_DIR)")
    ap.add_argument("--words", help="folder with the word notes (or DANSK_WORDS_DIR; default <data>/words)")
    ap.add_argument("--out", help="HTML file to write (default: system temp folder)")
    ap.add_argument("--today", help="treat this YYYY-MM-DD as today (for tests)")
    a = ap.parse_args(argv)

    data_dir = Path(a.data or os.environ.get("DANSK_DATA_DIR") or DEFAULT_DATA).expanduser()
    words_dir = Path(a.words or os.environ.get("DANSK_WORDS_DIR") or data_dir / "words").expanduser()
    out = Path(a.out).expanduser() if a.out else Path(tempfile.gettempdir()) / "dansk-dashboard.html"
    today = date.fromisoformat(a.today) if a.today else date.today()

    if not data_dir.is_dir():
        print(f"no data folder at {data_dir}: pass --data or set DANSK_DATA_DIR")
        return 1

    data = build_page(data_dir, words_dir, out, today)
    s = data["stats"]
    print(f"wrote {out}")
    print(f"  {s['words']} word notes, {s['grammar']} grammar notes, "
          f"{s['tracked']} tracked items, {s['due']} due on {s['today']}")
    if not data["words"]:
        print(f"  warning: no word notes found in {words_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
