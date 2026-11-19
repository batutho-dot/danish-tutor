"""Dashboard: JSON mode and database mode give the same numbers on the example data."""
import json
import unittest
from datetime import date

import helpers
import build_dashboard
import dansk_db
import import_fluent

TODAY = date(2026, 11, 6)
DUE = {"nøgle": ("2026-11-05", True), "morgenmad": ("2026-11-10", False),
       "at spise": ("2026-11-05", True), "ikke i bisætninger": ("2026-11-03", True)}


class Dashboard(helpers.TempCase):
    def imported(self):
        code, out = helpers.run_main(import_fluent.main, ["--data", str(helpers.EXAMPLE),
                                                          "--db", str(self.db)])
        self.assertEqual(code, 0, out)

    def test_json_mode_unchanged(self):
        d = build_dashboard.build_data(helpers.EXAMPLE, helpers.EXAMPLE / "words", TODAY)
        s = d["stats"]
        self.assertEqual((s["words"], s["grammar"], s["tracked"], s["due"]), (13, 1, 16, 15))

    def test_db_mode_matches_json_mode(self):
        self.imported()
        j = build_dashboard.build_data(helpers.EXAMPLE, helpers.EXAMPLE / "words", TODAY)
        d = build_dashboard.build_data_db(self.db, TODAY)
        for k in ("words", "grammar", "tracked", "due", "level", "target", "example_data"):
            self.assertEqual(d["stats"][k], j["stats"][k], k)
        by_head = {w["head"]: w for w in d["words"]}
        for head, (due, overdue) in DUE.items():
            self.assertEqual((by_head[head]["due"], by_head[head]["overdue"]), (due, overdue), head)
        jw = {w["head"]: w for w in j["words"]}
        for head, w in by_head.items():
            for k in ("forms", "da", "gloss", "ex", "mastery", "due"):
                self.assertEqual(w[k], jw[head][k], (head, k))
        self.assertEqual([p["wrong"] for p in d["patterns"]], [p["wrong"] for p in j["patterns"]])
        self.assertEqual({s["id"] for s in d["sessions"]}, {"example-session-001", "example-session-002"})

    def test_main_db_mode_writes_page(self):
        self.imported()
        out = self.tmp / "page.html"
        code, text = helpers.run_main(build_dashboard.main, ["--db", str(self.db), "--out", str(out),
                                                             "--today", "2026-11-06"])
        self.assertEqual(code, 0, text)
        self.assertIn("13 word notes, 1 grammar notes, 16 tracked items, 15 due on 2026-11-06", text)
        page = out.read_text(encoding="utf-8")
        self.assertIn('"head": "nøgle"', page)
        self.assertNotIn("/*__DATA__*/null", page)

    def test_default_is_configured_database(self):
        # DANISH_TUTOR_DB points into the temp folder (see helpers); nothing there yet.
        code, text = helpers.run_main(build_dashboard.main, ["--out", str(self.tmp / "p.html")])
        self.assertEqual(code, 1)
        self.assertIn("no database at", text)

    def test_recorded_session_shows_up(self):
        f = self.tmp / "p.json"
        f.write_text(json.dumps({
            "date": "2026-11-19", "duration_minutes": 5, "size": "small", "input_mode": "typed",
            "skills": ["speaking"], "new_words": [{"headword": "hus", "gloss": "house"}]}),
            encoding="utf-8")
        code, out = helpers.run_main(dansk_db.main, ["record", "--db", str(self.db), "--file", str(f)])
        self.assertEqual(code, 0, out)
        d = build_dashboard.build_data_db(self.db, date(2026, 11, 20))
        self.assertEqual((d["stats"]["words"], d["stats"]["due"], d["stats"]["sessions"]), (1, 1, 1))
        self.assertEqual(d["words"][0]["due"], "2026-11-20")

    def test_streak(self):
        self.assertEqual(build_dashboard.streak(["2026-11-01", "2026-11-03", "2026-11-04"]), 2)
        self.assertEqual(build_dashboard.streak([]), 0)

    def test_fold(self):
        self.assertEqual(build_dashboard.fold("Værelse"), "vaerelse")


if __name__ == "__main__":
    unittest.main()
