"""The local app server: security checks, the JSON API and writes, against a temp database
imported from example-data. The server runs in a thread on a free port; nothing outside the
temp folder is read or written (the static files come from a temp dist folder)."""
import http.client
import json
import threading

import helpers
import dansk_app
import dansk_db
import import_fluent

TODAY = "2026-11-06"


class AppServer(helpers.TempCase):
    def setUp(self):
        super().setUp()
        code, out = helpers.run_main(import_fluent.main, ["--data", str(helpers.EXAMPLE),
                                                          "--db", str(self.db)])
        self.assertEqual(code, 0, out)
        self.dist = self.tmp / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text(
            '<!doctype html><meta name="dansk-token" content="__DANSK_TOKEN__">'
            '<script type="module" src="./assets/app.js"></script>', encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
        (self.tmp / "secret.txt").write_text("outside dist", encoding="utf-8")
        self.srv = dansk_app.make_server(self.db, self.dist, port=0, today=TODAY, quiet=True)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.srv.port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)
        super().tearDown()

    def request(self, method, path, body=None, token=True, host=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        headers = {"Host": host or self.host}
        if token:
            headers["X-Dansk-Token"] = self.srv.token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            headers["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        payload = r.read()
        c.close()
        ctype = r.getheader("Content-Type") or ""
        return r.status, (json.loads(payload) if ctype.startswith("application/json") else payload)

    def item(self, iid):
        con = dansk_db.connect(self.db)
        try:
            it = dansk_db.get_item(con, iid)
            return dict(it) if it else None
        finally:
            con.close()

    # ---- security

    def test_no_token_is_403(self):
        status, body = self.request("GET", "/api/summary", token=False)
        self.assertEqual(status, 403)
        self.assertNotIn("today", body)

    def test_wrong_token_is_403(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request("GET", "/api/summary", headers={"Host": self.host, "X-Dansk-Token": "x" * 43})
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_bad_host_is_403(self):
        for host in ("evil.example:%d" % self.srv.port, "127.0.0.1", "localhost:1"):
            status, _ = self.request("GET", "/api/summary", host=host)
            self.assertEqual(status, 403, host)
        status, _ = self.request("GET", "/", host="evil.example:%d" % self.srv.port)
        self.assertEqual(status, 403)
        status, _ = self.request("GET", "/api/summary", host=f"localhost:{self.srv.port}")
        self.assertEqual(status, 200)

    def test_no_cors_headers(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request("GET", "/api/summary", headers={"Host": self.host, "X-Dansk-Token": self.srv.token,
                                                  "Origin": "http://evil.example"})
        r = c.getresponse()
        r.read()
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        c.close()

    def test_index_served_with_token(self):
        status, body = self.request("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(f'content="{self.srv.token}"'.encode(), body)
        self.assertNotIn(b"__DANSK_TOKEN__", body)
        status, body = self.request("GET", "/assets/app.js", token=False)
        self.assertEqual((status, body), (200, b"console.log(1)"))

    def test_path_traversal_blocked(self):
        for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt",
                     "/assets/%2e%2e/%2e%2e/secret.txt", "/..%5csecret.txt", "/%2fetc/passwd",
                     "/C:/Windows/win.ini"):
            status, body = self.request("GET", path, token=False)
            self.assertIn(status, (403, 404), path)
            self.assertNotIn(b"outside dist", body if isinstance(body, bytes) else b"", path)

    # ---- reads

    def test_summary_counts_match_example_data(self):
        status, s = self.request("GET", "/api/summary")
        self.assertEqual(status, 200)
        self.assertEqual((s["words"], s["grammar"], s["items"], s["due"], s["sessions"]),
                         (13, 1, 16, 15, 2))
        self.assertTrue(s["example_data"])
        self.assertEqual(s["minutes_week"], 20)        # 15 + 5 minutes, week of 2026-11-02
        self.assertEqual(len(s["days"]), 14)
        self.assertEqual(s["days"][-1]["date"], TODAY)
        self.assertEqual({p["id"] for p in s["patterns_due"]},
                         {"error_cykel_gender", "error_ikke_placement"})

    def test_due_oldest_first(self):
        _, d = self.request("GET", "/api/due")
        dates = [c["due_date"] for c in d["cards"]]
        self.assertEqual(len(dates), 15)
        self.assertEqual(dates, sorted(dates))
        noegle = next(c for c in d["cards"] if c["item_id"] == "vocab_noegle")
        self.assertEqual(noegle["gloss"], "key")
        self.assertTrue(noegle["examples"])

    def test_words_filters(self):
        _, w = self.request("GET", "/api/words")
        self.assertEqual(len(w["words"]), 14)
        _, w = self.request("GET", "/api/words?kind=grammar")
        self.assertEqual([x["headword"] for x in w["words"]], ["ikke i bisætninger"])
        _, w = self.request("GET", "/api/words?due=not_due")
        self.assertEqual([x["headword"] for x in w["words"]], ["morgenmad"])
        _, w = self.request("GET", "/api/words?q=KEY")
        self.assertEqual([x["headword"] for x in w["words"]], ["nøgle"])
        status, _ = self.request("GET", "/api/words?due=soon")
        self.assertEqual(status, 400)

    def test_sessions(self):
        _, s = self.request("GET", "/api/sessions")
        self.assertEqual([x["id"] for x in s["sessions"]], ["example-session-002", "example-session-001"])
        status, d = self.request("GET", "/api/sessions/example-session-001")
        self.assertEqual(status, 200)
        self.assertEqual(d["duration_minutes"], 15)
        status, _ = self.request("GET", "/api/sessions/nope")
        self.assertEqual(status, 404)

    # ---- review

    def test_preview_fresh_item(self):
        con = dansk_db.connect(self.db)
        with con:
            dansk_db.insert_item(con, {"id": "vocab_fresh", "kind": "vocabulary", "content": "frisk",
                                       "due_date": TODAY})
        con.close()
        status, p = self.request("GET", "/api/review/preview?item_id=vocab_fresh")
        self.assertEqual(status, 200)
        by_q = {o["quality"]: o for o in p["options"]}
        self.assertEqual(sorted(by_q), [1, 3, 4, 5])
        self.assertEqual(by_q[4]["interval_days"], 1)
        self.assertEqual(by_q[4]["due_date"], "2026-11-07")
        self.assertEqual(by_q[1]["interval_days"], 1)
        self.assertEqual(by_q[5]["easiness_factor"], 2.6)
        self.assertEqual(self.item("vocab_fresh")["total_reviews"], 0)   # preview writes nothing

    def test_review_applies_sm2(self):
        before = self.item("vocab_noegle")
        ef, interval, reps = dansk_db.sm2(4, before["easiness_factor"], before["interval_days"],
                                          before["repetitions"])
        status, r = self.request("POST", "/api/review",
                                 {"item_id": "vocab_noegle", "quality": 4, "elapsed_seconds": 90})
        self.assertEqual(status, 200, r)
        after = self.item("vocab_noegle")
        self.assertEqual((after["easiness_factor"], after["interval_days"], after["repetitions"]),
                         (ef, interval, reps))
        self.assertEqual(after["due_date"], dansk_db.add_days(TODAY, interval))
        self.assertEqual(after["total_reviews"], before["total_reviews"] + 1)
        self.assertEqual(r["session_id"], f"app-review-{TODAY}")
        con = dansk_db.connect(self.db)
        try:
            rev = con.execute("SELECT session_id, date, quality, interval_after FROM reviews").fetchall()
            sess = dansk_db.get_session(con, f"app-review-{TODAY}")
        finally:
            con.close()
        self.assertEqual([tuple(x) for x in rev], [(f"app-review-{TODAY}", TODAY, 4, interval)])
        self.assertEqual((sess["input_mode"], sess["size"], sess["skills"], sess["duration_minutes"]),
                         ("typed", "small", ["vocabulary"], 2))
        # A second review the same day joins the same session row.
        self.request("POST", "/api/review", {"item_id": "vocab_hus", "quality": 1, "elapsed_seconds": 30})
        _, s = self.request("GET", "/api/sessions")
        app = [x for x in s["sessions"] if x["id"].startswith("app-review-")]
        self.assertEqual(len(app), 1)
        self.assertEqual((app[0]["reviews"], app[0]["duration_minutes"]), (2, 2))

    def test_bad_review_payloads_change_nothing(self):
        before = self.item("vocab_noegle")
        bad = [{"item_id": "vocab_noegle", "quality": 6}, {"item_id": "vocab_noegle", "quality": "4"},
               {"item_id": "vocab_noegle", "quality": True}, {"item_id": "nope", "quality": 4},
               {"item_id": "vocab_noegle", "quality": 4, "extra": 1}, [1, 2],
               {"item_id": "vocab_noegle", "quality": 4, "elapsed_seconds": -1}]
        for b in bad:
            status, body = self.request("POST", "/api/review", b)
            self.assertEqual(status, 400, b)
            self.assertIn("error", body)
        status, body = self.request("POST", "/api/review", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(self.item("vocab_noegle"), before)
        _, s = self.request("GET", "/api/sessions")
        self.assertEqual(len(s["sessions"]), 2)

    # ---- edit and delete

    def word_id(self, head):
        con = dansk_db.connect(self.db)
        try:
            return dansk_db.find_word(con, head)["id"]
        finally:
            con.close()

    def test_edit_persists(self):
        wid = self.word_id("nøgle")
        status, w = self.request("PUT", f"/api/words/{wid}",
                                 {"gloss": "key (for a door)", "notes": "edited in a test", "level": "A2"})
        self.assertEqual(status, 200, w)
        con = dansk_db.connect(self.db)
        try:
            row = dansk_db.get_word(con, wid)
            it = dansk_db.get_item(con, "vocab_noegle")
        finally:
            con.close()
        self.assertEqual((row["gloss"], row["notes"], row["level"]), ("key (for a door)", "edited in a test", "A2"))
        self.assertEqual(it["answer"], "key (for a door)")

    def test_bad_edit_changes_nothing(self):
        wid = self.word_id("nøgle")
        _, before = self.request("GET", f"/api/words/{wid}")
        other = self.word_id("hus")
        for b in ({"headword": ""}, {"kind": "grammar"}, {"gloss": 5}, {}, {"headword": "hus"},
                  {"gloss": "x" * 5000}):
            status, body = self.request("PUT", f"/api/words/{wid}", b)
            self.assertEqual(status, 400, (b, body))
        _, after = self.request("GET", f"/api/words/{wid}")
        self.assertEqual(after, before)
        self.assertNotEqual(other, wid)
        status, _ = self.request("PUT", "/api/words/99999", {"gloss": "x"})
        self.assertEqual(status, 404)

    def test_delete_removes_word_item_examples_reviews(self):
        self.request("POST", "/api/review", {"item_id": "vocab_noegle", "quality": 5})
        wid = self.word_id("nøgle")
        status, d = self.request("DELETE", f"/api/words/{wid}")
        self.assertEqual(status, 200, d)
        self.assertEqual(d["deleted"]["words"], 1)
        self.assertEqual(d["deleted"]["items"], 1)
        self.assertGreaterEqual(d["deleted"]["examples"], 1)
        self.assertEqual(d["deleted"]["reviews"], 1)
        con = dansk_db.connect(self.db)
        try:
            self.assertIsNone(dansk_db.find_word(con, "nøgle"))
            self.assertIsNone(dansk_db.get_item(con, "vocab_noegle"))
            n_ex = con.execute("SELECT COUNT(*) FROM examples WHERE word_id = ?", (wid,)).fetchone()[0]
            n_rev = con.execute("SELECT COUNT(*) FROM reviews WHERE item_id = 'vocab_noegle'").fetchone()[0]
        finally:
            con.close()
        self.assertEqual((n_ex, n_rev), (0, 0))
        status, _ = self.request("DELETE", f"/api/words/{wid}")
        self.assertEqual(status, 404)

    def test_unknown_route_and_method(self):
        self.assertEqual(self.request("GET", "/api/nope")[0], 404)
        self.assertEqual(self.request("POST", "/api/summary", {})[0], 405)
        self.assertEqual(self.request("POST", "/", {}, token=False)[0], 405)


class Streak(helpers.TempCase):
    def test_current_streak(self):
        f = dansk_app.current_streak
        self.assertEqual(f(["2026-11-04", "2026-11-05", "2026-11-06"], "2026-11-06"), 3)
        self.assertEqual(f(["2026-11-04", "2026-11-05"], "2026-11-06"), 2)
        self.assertEqual(f(["2026-11-02", "2026-11-04"], "2026-11-06"), 0)
        self.assertEqual(f([], "2026-11-06"), 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
