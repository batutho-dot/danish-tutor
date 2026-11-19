"""Error cards: schema migration, mistakes-db import, split pairs, item edit and delete API.
Temp folders and invented data only."""
import json
import sqlite3

import helpers
import dansk_db
import import_fluent
from test_app import ServerBase

V1_ITEMS = """CREATE TABLE items (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT, answer TEXT, category TEXT,
    difficulty TEXT, word_id INTEGER, easiness_factor REAL NOT NULL,
    interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL, due_date TEXT,
    last_reviewed TEXT, total_reviews INTEGER NOT NULL, mastery_level INTEGER NOT NULL)"""


class Migration(helpers.TempCase):
    def test_v1_database_gains_columns_and_keeps_rows(self):
        con = sqlite3.connect(str(self.db))
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        con.execute(V1_ITEMS)
        con.execute("INSERT INTO items VALUES ('error_x', 'error_pattern', 'a', 'b', 'grammar',"
                    " NULL, NULL, 2.5, 1, 0, '2026-11-01', NULL, 0, 0)")
        con.commit()
        con.close()
        con = dansk_db.connect(self.db)
        try:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
            self.assertTrue({"description", "context", "noted"} <= cols)
            self.assertEqual(dansk_db.get_meta(con, "schema_version"), "2")
            it = dansk_db.get_item(con, "error_x")
            self.assertEqual((it["content"], it["answer"], it["description"]), ("a", "b", None))
        finally:
            con.close()
        con = dansk_db.connect(self.db)          # a second open changes nothing
        self.assertEqual(dansk_db.get_meta(con, "schema_version"), "2")
        con.close()

    def test_new_database_is_v2(self):
        con = dansk_db.connect(self.db)
        self.assertEqual(dansk_db.get_meta(con, "schema_version"), dansk_db.SCHEMA_VERSION)
        con.close()


class Pairs(helpers.TempCase):
    def test_split_only_when_both_sides_match(self):
        self.assertEqual(dansk_db.error_pairs("at bowl / at flytte", "en noegle / flyttet"),
                         [["at bowl", "en noegle"], ["at flytte", "flyttet"]])
        self.assertEqual(dansk_db.error_pairs("a / b / c", "x / y"), [["a / b / c", "x / y"]])
        self.assertEqual(dansk_db.error_pairs("et ny cykel", "en ny cykel"),
                         [["et ny cykel", "en ny cykel"]])
        self.assertEqual(dansk_db.error_pairs(None, None), [["", ""]])


class MistakesImport(helpers.TempCase):
    def import_dir(self, mdb):
        d = self.tmp / "fluent"
        d.mkdir(exist_ok=True)
        (d / "spaced-repetition.json").write_text(json.dumps({"items": {
            "error_glued": {"id": "error_glued", "type": "error_pattern",
                            "content": "at bowl / at flytte", "answer": "en noegle / flyttet",
                            "category": "grammar", "due_date": "2026-11-06"},
            "error_bare": {"id": "error_bare", "type": "error_pattern", "due_date": "2026-11-06"}}}),
            encoding="utf-8")
        if mdb is not None:
            (d / "mistakes-db.json").write_text(json.dumps(mdb, ensure_ascii=False), encoding="utf-8")
        return helpers.run_main(import_fluent.main, ["--data", str(d), "--db", str(self.db)])

    def test_description_context_and_date_attached(self):
        mdb = {"error_patterns": {
            "glued": {"category": "grammar", "description": "Invented description.",
                      "severity": "minor", "frequency": 2, "surprise_key": [1],
                      "examples": [{"incorrect": "x", "correct": "y", "context": "old", "date": "2026-10-01"},
                                   {"incorrect": "at bowl", "correct": "en noegle",
                                    "context": "Latest invented context.", "date": "2026-11-02"}]},
            "error_bare": {"description": "Bare item.",
                           "examples": [{"incorrect": "jeg har ikke", "correct": "jeg ikke har",
                                         "date": "2026-11-03"}]},
            "no_such_item": {"description": "ignored"}}}
        code, out = self.import_dir(mdb)
        self.assertEqual(code, 0, out)
        self.assertIn("notes on 2 error items", out)
        con = dansk_db.connect(self.db)
        try:
            g = dansk_db.get_item(con, "error_glued")
            b = dansk_db.get_item(con, "error_bare")
            self.assertEqual((g["description"], g["context"], g["noted"]),
                             ("Invented description.", "Latest invented context.", "2026-11-02"))
            self.assertEqual((g["content"], g["answer"]), ("at bowl / at flytte", "en noegle / flyttet"))
            self.assertEqual((b["content"], b["answer"], b["description"]),
                             ("jeg har ikke", "jeg ikke har", "Bare item."))
            self.assertIsNone(dansk_db.get_item(con, "error_no_such_item"))
            # An edit made in the app is not overwritten by a rerun.
            with con:
                dansk_db.update_item(con, "error_glued", {"description": "Edited."})
        finally:
            con.close()
        code, out = self.import_dir(mdb)
        self.assertIn("notes on 0 error items", out)
        con = dansk_db.connect(self.db)
        try:
            self.assertEqual(dansk_db.get_item(con, "error_glued")["description"], "Edited.")
            card = next(c for c in dansk_db.due_cards(con, "2026-11-06") if c["item_id"] == "error_glued")
        finally:
            con.close()
        self.assertEqual(card["pairs"], [["at bowl", "en noegle"], ["at flytte", "flyttet"]])
        self.assertEqual((card["context"], card["mistake_date"]), ("Latest invented context.", "2026-11-02"))

    def test_absent_or_odd_mistakes_file(self):
        for mdb in (None, {}, {"error_patterns": []}, {"error_patterns": {"glued": "not a dict"}},
                    {"error_patterns": [{"pattern_id": "error_glued", "description": "From a list."}]}):
            code, out = self.import_dir(mdb)
            self.assertEqual(code, 0, (mdb, out))
        con = dansk_db.connect(self.db)
        self.assertEqual(dansk_db.get_item(con, "error_glued")["description"], "From a list.")
        con.close()

    def test_example_data_cards(self):
        code, out = helpers.run_main(import_fluent.main, ["--data", str(helpers.EXAMPLE),
                                                          "--db", str(self.db)])
        self.assertEqual(code, 0, out)
        con = dansk_db.connect(self.db)
        try:
            cards = {c["item_id"]: c for c in dansk_db.due_cards(con, "2026-11-06")}
        finally:
            con.close()
        c = cards["error_ikke_placement"]
        self.assertTrue(c["description"].startswith("In a subordinate clause"))
        self.assertEqual(c["mistake_date"], "2026-11-02")
        self.assertEqual(c["repetitions"], 0)
        self.assertIsNone(cards["vocab_noegle"]["context"])

    def test_record_sets_context_and_date(self):
        con = dansk_db.connect(self.db)
        p = {"date": "2026-11-19", "duration_minutes": 5, "size": "small", "input_mode": "typed",
             "errors": [{"pattern_id": "ikke_placement", "said": "a", "correct": "b",
                         "context": "Invented."}]}
        with con:
            dansk_db.apply_record(con, p, {})
        it = dansk_db.get_item(con, "error_ikke_placement")
        con.close()
        self.assertEqual((it["context"], it["noted"]), ("Invented.", "2026-11-19"))


class ItemApi(ServerBase):
    def test_edit_item_persists(self):
        status, it = self.request("PUT", "/api/items/error_ikke_placement",
                                  {"content": "fordi jeg har ikke tid", "answer": "fordi jeg ikke har tid",
                                   "description": "Edited in a test.", "context": ""})
        self.assertEqual(status, 200, it)
        self.assertEqual(it["description"], "Edited in a test.")
        self.assertIsNone(it["context"])
        self.assertEqual(self.item("error_ikke_placement")["description"], "Edited in a test.")

    def test_bad_item_edit_changes_nothing(self):
        before = self.item("error_cykel_gender")
        for b in ({"content": ""}, {"answer": "  "}, {"due_date": "2030-01-01"}, {}, {"content": 3},
                  {"description": "x" * 5000}, [1]):
            status, body = self.request("PUT", "/api/items/error_cykel_gender", b)
            self.assertEqual(status, 400, (b, body))
        self.assertEqual(self.item("error_cykel_gender"), before)
        status, _ = self.request("PUT", "/api/items/nope", {"content": "x"})
        self.assertEqual(status, 404)

    def test_delete_item_and_reviews(self):
        self.request("POST", "/api/review", {"item_id": "error_cykel_gender", "quality": 1})
        status, d = self.request("DELETE", "/api/items/error_cykel_gender")
        self.assertEqual(status, 200, d)
        self.assertEqual(d["deleted"], {"items": 1, "reviews": 1})
        self.assertIsNone(self.item("error_cykel_gender"))
        status, _ = self.request("DELETE", "/api/items/error_cykel_gender")
        self.assertEqual(status, 404)

    def test_due_cards_carry_error_fields(self):
        status, d = self.request("GET", "/api/due")
        self.assertEqual(status, 200)
        c = next(x for x in d["cards"] if x["item_id"] == "error_cykel_gender")
        self.assertEqual(c["pairs"], [["et ny cykel", "en ny cykel"]])
        self.assertEqual(c["context"], "Talking about how you get to work.")
        self.assertIn("common-gender", c["description"])
