#!/usr/bin/env python3
"""One-way import from Fluent-format JSON files (and optional markdown word notes) into the
danish-tutor database.

    python import_fluent.py --data DIR [--words DIR] [--db PATH]

Reads from DIR, each file optional:
  spaced-repetition.json   items (object keyed by id, or a list); keys id/type or
                           item_id/item_type; type vocabulary, grammar, grammar_rule or
                           error_pattern; schedule fields copied when present
  session-log.json         sessions
  learner-profile.json     learner level, target level, native language
  mistakes-db.json         error patterns: a pattern's description and its latest example's
                           context and date go onto the matching error item (id, or
                           error_<id>); unknown keys are ignored, missing ones skipped
Word notes (--words, default DIR/words when that folder exists) are parsed the same way the
dashboard parses them.

Idempotent: a word, item or session that is already in the database (same headword or id) is
left as it is, so running the import twice adds nothing the second time. It never writes to
the source folders. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dansk_db  # noqa: E402
import dansk_text  # noqa: E402

KINDS = {"vocabulary": "vocabulary", "grammar": "grammar", "grammar_rule": "grammar",
         "error_pattern": "error_pattern"}


def load_json(folder: Path, name: str) -> dict:
    p = folder / name
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def iter_items(sr: dict):
    items = sr.get("items") or {}
    if isinstance(items, dict):
        for key, it in items.items():
            if isinstance(it, dict):
                yield key, it
    elif isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                yield None, it


def _text(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def iter_patterns(mdb: dict):
    pats = mdb.get("error_patterns") or {}
    if isinstance(pats, dict):
        for key, pat in pats.items():
            if isinstance(pat, dict):
                yield str(key), pat
    elif isinstance(pats, list):
        for pat in pats:
            if isinstance(pat, dict) and (pat.get("id") or pat.get("pattern_id")):
                yield str(pat.get("id") or pat.get("pattern_id")), pat


def import_mistakes(con, mdb: dict) -> int:
    """Fluent's mistakes-db.json: {"error_patterns": {<id>: {"description", "examples":
    [{"incorrect", "correct", "context", "date"}], ...}}}. Adds the description and the latest
    example's context and date to the matching error item (id as given, or error_<id>), only
    where those fields are still empty, so a rerun or an edit in the app is never overwritten.
    An item with no content or answer gets the latest example's wording. No item is created.
    Returns how many items gained something."""
    n = 0
    for key, pat in iter_patterns(mdb):
        it = dansk_db.get_item(con, key) or dansk_db.get_item(con, dansk_db.error_item_id(key))
        if it is None:
            continue
        examples = [e for e in pat.get("examples") or [] if isinstance(e, dict)]
        latest = max(examples, key=lambda e: str(e.get("date") or ""), default={})
        day = str(latest.get("date") or pat.get("last_occurred") or pat.get("last_seen") or "")[:10]
        new = {"description": _text(pat.get("description")), "context": _text(latest.get("context")),
               "noted": day if dansk_db.is_date(day) else None,
               "content": _text(latest.get("incorrect")), "answer": _text(latest.get("correct"))}
        fields = {k: v for k, v in new.items() if v and not it[k]}
        if fields:
            for k, v in fields.items():
                con.execute(f"UPDATE items SET {k} = ? WHERE id = ?", (v, it["id"]))
            n += 1
    return n


def import_all(con, data_dir: Path, words_dir: Path | None) -> dict:
    """Import into an open connection. Caller owns the transaction. Returns counts added."""
    added = {"words": 0, "examples": 0, "items": 0, "sessions": 0, "skipped_items": 0,
             "error_notes": 0}

    sr = load_json(data_dir, "spaced-repetition.json")
    profile = load_json(data_dir, "learner-profile.json")
    log = load_json(data_dir, "session-log.json")
    if sr.get("_note") or profile.get("_note"):
        dansk_db.set_meta(con, "example_data", "true")

    learner = profile.get("learner") or {}
    fields = {"level": learner.get("current_level"), "target_level": learner.get("target_level"),
              "support_language": learner.get("native_language")}
    fields = {k: v for k, v in fields.items() if v}
    if fields:
        dansk_db.set_learner(con, **fields)

    # Word notes first, so items can be linked to them.
    word_ids: dict[str, int] = {}
    if words_dir is not None:
        for w in dansk_text.read_words(words_dir):
            row = dansk_db.find_word(con, w["head"])
            if row is None:
                wid = dansk_db.insert_word(con, {
                    "headword": w["head"], "kind": w["kind"], "pos": w["pos"] or None,
                    "gender": w["gender"] or None, "level": w["level"] or None,
                    "forms": w["forms"] or None, "definition": w["da"] or None,
                    "gloss": w["gloss"] or None, "notes": w["notes"] or None,
                    "learned": w["learned"] or None, "source": w["source"] or None})
                added["words"] += 1
            else:
                wid = row["id"]
            for ex in w["ex"]:
                if not dansk_db.has_example(con, wid, ex):
                    dansk_db.insert_example(con, wid, ex, w["source"] or None)
                    added["examples"] += 1
            word_ids[dansk_text.item_key(w["head"])] = wid

    for key, it in iter_items(sr):
        iid = it.get("id") or it.get("item_id") or key
        kind = KINDS.get(it.get("type") or it.get("item_type") or "")
        if not iid or not kind:
            added["skipped_items"] += 1
            continue
        if dansk_db.get_item(con, iid) is not None:
            continue
        stem = iid.split("_", 1)[1] if iid.startswith(("vocab_", "grammar_")) else None
        dansk_db.insert_item(con, {
            "id": iid, "kind": kind, "content": it.get("content"), "answer": it.get("answer"),
            "category": it.get("category"), "difficulty": it.get("difficulty"),
            "word_id": word_ids.get(stem) if stem else None,
            "easiness_factor": it.get("easiness_factor"),
            "interval_days": it.get("interval_days") or it.get("interval"),
            "repetitions": it.get("repetitions"), "due_date": it.get("due_date"),
            "last_reviewed": it.get("last_reviewed"), "total_reviews": it.get("total_reviews"),
            "mastery_level": it.get("mastery_level")})
        added["items"] += 1

    added["error_notes"] = import_mistakes(con, load_json(data_dir, "mistakes-db.json"))

    for s in log.get("sessions") or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("session_id") or s.get("id")
        day = str(s.get("date") or "")[:10]
        if not sid or not dansk_db.is_date(day) or dansk_db.session_exists(con, sid):
            continue
        dansk_db.insert_session(con, {
            "id": sid, "date": day,
            "duration_minutes": s.get("duration_minutes") or s.get("duration"),
            "size": s.get("size"), "input_mode": s.get("input_mode"), "topic": s.get("topic"),
            "skills": s.get("skills_practiced") or s.get("skills") or [],
            "accuracy": s.get("accuracy"), "summary": s.get("notes") or s.get("summary")})
        added["sessions"] += 1
    return added


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Import Fluent-format JSON into the danish-tutor database")
    ap.add_argument("--data", required=True, help="folder with the Fluent JSON files")
    ap.add_argument("--words", help="folder with markdown word notes (default <data>/words if present)")
    ap.add_argument("--db", help="database file (default: the configured path)")
    a = ap.parse_args(argv)

    data_dir = Path(a.data).expanduser()
    if not data_dir.is_dir():
        print(f"no folder at {data_dir}")
        return 1
    if a.words:
        words_dir = Path(a.words).expanduser()
        if not words_dir.is_dir():
            print(f"no folder at {words_dir}")
            return 1
    else:
        words_dir = data_dir / "words" if (data_dir / "words").is_dir() else None

    path = dansk_db.db_path(a.db)
    try:
        con = dansk_db.connect(path)
        with con:
            added = import_all(con, data_dir, words_dir)
        c = dansk_db.counts(con)
        con.close()
    except json.JSONDecodeError as e:
        print(f"not imported: a JSON file could not be read: {e}")
        return 1
    except Exception as e:                      # report, nothing committed
        print(f"not imported: {type(e).__name__}: {e}")
        return 2
    print(f"imported into {path}")
    print(f"  added {added['words']} words, {added['examples']} examples, {added['items']} items, "
          f"{added['sessions']} sessions, notes on {added['error_notes']} error items" +
          (f"; skipped {added['skipped_items']} items without id or known type"
           if added["skipped_items"] else ""))
    print(f"  database now holds {c['words']} words, {c['grammar']} grammar notes, "
          f"{c['items']} items, {c['sessions']} sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
