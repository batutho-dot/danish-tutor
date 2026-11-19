"""The SQLite store: record, validation, rollback, notes, import. Temp folders only."""
import json
import sqlite3
import unittest
from unittest import mock

import helpers
import dansk_db
import import_fluent

DAY = "2026-11-19"


def payload(**over):
    p = {
        "date": DAY, "duration_minutes": 15, "size": "large", "input_mode": "voice",
        "topic": "invented test topic", "summary": "Invented test session.",
        "skills": ["speaking", "listening"], "accuracy": 0.5,
        "new_words": [{"headword": "nøgle", "kind": "word", "pos": "noun", "gender": "fælleskøn",
                       "level": "A1", "forms": "en nøgle, nøglen, nøgler, nøglerne",
                       "definition": "Den bruger man til at låse en dør op.", "gloss": "key",
                       "example": "Jeg har glemt min nøgle.", "category": "home"}],
        "errors": [{"pattern_id": "ikke_placement", "category": "grammar",
                    "said": "fordi jeg har ikke tid", "correct": "fordi jeg ikke har tid",
                    "context": "invented", "severity": "moderate"}],
        "listening": [{"sentence": "Hvor har du lagt nøglen?", "result": "gist_only"}],
    }
    p.update(over)
    return p


class Store(helpers.TempCase):
    def record(self, p, extra=()):
        f = self.tmp / "payload.json"
        f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        return helpers.run_main(dansk_db.main, ["record", "--db", str(self.db), "--file", str(f), *extra])

    def con(self):
        return dansk_db.connect(self.db)

    def test_round_trip(self):
        code, out = self.record(payload())
        self.assertEqual(code, 0, out)
        self.assertIn(f"saved session-{DAY}, 0 reviews, 1 new words, 1 errors; 2 items due tomorrow", out)
        con = self.con()
        w = dansk_db.find_word(con, "nøgle")
        self.assertEqual(w["gloss"], "key")
        ex = [r["sentence"] for r in con.execute("SELECT sentence FROM examples WHERE word_id = ?", (w["id"],))]
        self.assertEqual(ex, ["Jeg har glemt min nøgle."])
        it = dansk_db.get_item(con, "vocab_noegle")
        self.assertEqual((it["kind"], it["due_date"], it["easiness_factor"], it["word_id"]),
                         ("vocabulary", "2026-11-20", 2.5, w["id"]))
        err = dansk_db.get_item(con, "error_ikke_placement")
        self.assertEqual((err["content"], err["answer"], err["due_date"]),
                         ("fordi jeg har ikke tid", "fordi jeg ikke har tid", "2026-11-20"))
        self.assertTrue(dansk_db.session_exists(con, f"session-{DAY}"))
        self.assertEqual(dansk_db.counts(con)["listening"], 1)
        con.close()

    def test_review_runs_sm2_and_second_session_same_day(self):
        self.assertEqual(self.record(payload())[0], 0)
        p = payload(new_words=[{"headword": "nøgle", "example": "Nøglen ligger på bordet."}],
                    errors=[], listening=[], reviews=[{"item_id": "vocab_noegle", "quality": 5}])
        code, out = self.record(p)
        self.assertEqual(code, 0, out)
        self.assertIn(f"saved session-{DAY}-2, 1 reviews, 0 new words, 0 errors", out)
        con = self.con()
        it = dansk_db.get_item(con, "vocab_noegle")
        self.assertEqual((it["easiness_factor"], it["interval_days"], it["repetitions"],
                          it["due_date"], it["total_reviews"], it["mastery_level"]),
                         (2.6, 1, 1, "2026-11-20", 1, 1))
        self.assertEqual(dansk_db.counts(con)["words"], 1)
        n = con.execute("SELECT COUNT(*) FROM examples").fetchone()[0]
        self.assertEqual(n, 2)                  # existing word: example added, no new word
        rv = con.execute("SELECT quality, ef_after, interval_after FROM reviews").fetchone()
        self.assertEqual(tuple(rv), (5, 2.6, 1))
        con.close()

    def test_existing_word_keeps_schedule(self):
        self.record(payload())
        self.record(payload(errors=[], listening=[], reviews=[{"item_id": "vocab_noegle", "quality": 5}]))
        self.record(payload(date="2026-11-21", errors=[], listening=[]))   # same word again
        con = self.con()
        it = dansk_db.get_item(con, "vocab_noegle")
        self.assertEqual((it["repetitions"], it["due_date"]), (1, "2026-11-20"))
        con.close()

    def test_repeated_error_resets_item(self):
        self.record(payload())
        con = self.con()
        with con:
            dansk_db.update_schedule(con, "error_ikke_placement", 2.2, 6, 2, "2026-12-01", DAY, True)
        con.close()
        self.record(payload(date="2026-11-25", new_words=[], listening=[]))
        con = self.con()
        it = dansk_db.get_item(con, "error_ikke_placement")
        self.assertEqual((it["easiness_factor"], it["interval_days"], it["repetitions"], it["due_date"]),
                         (2.2, 1, 0, "2026-11-26"))
        self.assertEqual(dansk_db.counts(con)["errors"], 2)
        con.close()

    def assert_nothing_written(self):
        con = self.con()
        c = dansk_db.counts(con)
        con.close()
        self.assertEqual((c["sessions"], c["words"], c["items"], c["errors"], c["listening"]),
                         (0, 0, 0, 0, 0))

    def test_invalid_payload_writes_nothing(self):
        bad = [
            payload(date="19-11-2026"),
            payload(size="medium"),
            payload(reviews=[{"item_id": "vocab_missing", "quality": 4}]),
            payload(reviews=[{"item_id": "vocab_noegle", "quality": 7}]),
            payload(listening=[{"sentence": "Hej", "result": "heard"}]),
            payload(errors=[{"pattern_id": "Bad Id", "said": "x", "correct": "y"}]),
            payload(new_words=[{"headword": ""}]),
            payload(surprise=1),
        ]
        for p in bad:
            code, out = self.record(p)
            self.assertEqual(code, 1, (p, out))
            self.assertIn("not saved", out)
        self.assert_nothing_written()

    def test_not_json(self):
        f = self.tmp / "p.json"
        f.write_text("{not json", encoding="utf-8")
        code, out = helpers.run_main(dansk_db.main, ["record", "--db", str(self.db), "--file", str(f)])
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", out)

    def test_db_error_rolls_back(self):
        with mock.patch.object(dansk_db, "insert_listening",
                               side_effect=sqlite3.OperationalError("disk I/O error")):
            code, out = self.record(payload())
        self.assertEqual(code, 2, out)
        self.assertIn("nothing written", out)
        self.assert_nothing_written()

    def test_notes_dir(self):
        notes = self.tmp / "notes"
        (self.tmp / "config.json").write_text(json.dumps({"notes_dir": str(notes)}), encoding="utf-8")
        code, out = self.record(payload(new_words=payload()["new_words"] + [
            {"headword": "at købe", "kind": "word", "pos": "verb", "gloss": "to buy"}]))
        self.assertEqual(code, 0, out)
        word = (notes / "words" / "noegle.md").read_text(encoding="utf-8")
        self.assertIn('title: "nøgle"', word)
        self.assertIn(f"- Jeg har glemt min nøgle. ([[dansk-session-{DAY}]])", word)
        self.assertTrue((notes / "words" / "koebe.md").is_file())
        sess = (notes / "sessions" / f"dansk-session-{DAY}.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | Hvor har du lagt nøglen? | gist_only |", sess)
        self.assertIn("[[noegle|nøgle]]", sess)
        # A later example for the same word lands in the existing note's Eksempler section.
        self.record(payload(date="2026-11-20", errors=[], listening=[],
                            new_words=[{"headword": "nøgle", "example": "Nøglen er væk."}]))
        word = (notes / "words" / "noegle.md").read_text(encoding="utf-8")
        eks = word.split("## Eksempler", 1)[1].split("##", 1)[0]
        self.assertIn("Nøglen er væk. ([[dansk-session-2026-11-20]])", eks)
        # The dashboard's own parser reads the written note back.
        import dansk_text
        parsed = {w["head"]: w for w in dansk_text.read_words(notes / "words")}
        self.assertEqual(parsed["nøgle"]["gloss"], "key")
        self.assertEqual(parsed["nøgle"]["forms"], "en nøgle, nøglen, nøgler, nøglerne")

    def test_due_and_words(self):
        self.record(payload())
        code, out = helpers.run_main(dansk_db.main, ["due", "--db", str(self.db), "--json",
                                                     "--today", "2026-11-20"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(sorted(i["id"] for i in d["due_items"]), ["error_ikke_placement", "vocab_noegle"])
        self.assertEqual(d["error_patterns"][0]["pattern_id"], "ikke_placement")
        self.assertFalse(d["first_session"])
        code, out = helpers.run_main(dansk_db.main, ["words", "--db", str(self.db), "--json"])
        self.assertEqual([w["headword"] for w in json.loads(out)], ["nøgle"])

    def test_due_without_database_does_not_create_it(self):
        code, out = helpers.run_main(dansk_db.main, ["due", "--db", str(self.db), "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["first_session"])
        self.assertFalse(self.db.exists())

    def test_db_path_order(self):
        import os
        self.assertEqual(dansk_db.db_path(str(self.tmp / "a.db")), self.tmp / "a.db")
        self.assertEqual(dansk_db.db_path(), self.tmp / "default.db")
        os.environ.pop("DANISH_TUTOR_DB")
        self.assertEqual(dansk_db.db_path(None, {"db_path": str(self.tmp / "c.db")}), self.tmp / "c.db")

    def test_import_is_idempotent(self):
        for _ in range(2):
            code, out = helpers.run_main(import_fluent.main, ["--data", str(helpers.EXAMPLE),
                                                              "--db", str(self.db)])
            self.assertEqual(code, 0, out)
        self.assertIn("added 0 words, 0 examples, 0 items, 0 sessions", out)
        con = self.con()
        c = dansk_db.counts(con)
        self.assertEqual((c["words"], c["grammar"], c["items"], c["sessions"]), (13, 1, 16, 2))
        it = dansk_db.get_item(con, "vocab_noegle")
        self.assertEqual((it["easiness_factor"], it["due_date"], it["total_reviews"], it["mastery_level"]),
                         (2.18, "2026-11-05", 2, 0))
        self.assertIsNotNone(it["word_id"])
        self.assertEqual(dansk_db.get_learner(con)["level"], "A2")
        con.close()

    def test_import_alternative_keys(self):
        src = self.tmp / "fluent"
        src.mkdir()
        (src / "spaced-repetition.json").write_text(json.dumps({"items": [
            {"item_id": "grammar_v2", "item_type": "grammar_rule", "content": "V2",
             "easiness_factor": 2.3, "interval_days": 6, "repetitions": 2, "due_date": "2026-11-30"},
            {"item_id": "odd", "item_type": "unknown"}]}), encoding="utf-8")
        code, out = helpers.run_main(import_fluent.main, ["--data", str(src), "--db", str(self.db)])
        self.assertEqual(code, 0, out)
        self.assertIn("skipped 1 items", out)
        con = self.con()
        it = dansk_db.get_item(con, "grammar_v2")
        self.assertEqual((it["kind"], it["interval_days"], it["repetitions"], it["mastery_level"]),
                         ("grammar", 6, 2, 2))
        con.close()


if __name__ == "__main__":
    unittest.main()
