"""Practice sessions in the app, end to end against the FAKE tutor backend (tests/fake_tutor.py,
via DANISH_TUTOR_BACKEND). The Anthropic API is never called here. Temp folders and invented
data only."""
import json
import os
import time
from pathlib import Path
from unittest import mock

import helpers
import dansk_app
import dansk_db
import dansk_practice
import dansk_tutor
from test_app import ServerBase

FAKE = str(Path(__file__).resolve().parent / "fake_tutor.py")
SENTENCE = "Hvor har du lagt nøglen?"
TEXT = ("Godt. Nu laver vi en lytteøvelse.\n\n<listen>" + SENTENCE + "</listen>\n\n"
        "\U0001f50a Sætning 2 af 5. \U0001f3a4 **Hvad hørte du?**\n")


def run_filter(text, size):
    f = dansk_practice.StreamFilter()
    evs = []
    for i in range(0, len(text), size):
        evs += f.feed(text[i:i + size])
    return evs + f.flush()


class Filter(helpers.TempCase):
    def test_every_split_strips_listen_and_signal(self):
        for size in range(1, len(TEXT) + 1):
            evs = run_filter(TEXT, size)
            shown = "".join(e[1] for e in evs if e[0] == "text")
            self.assertNotIn("nøglen", shown, size)
            self.assertNotIn("listen", shown, size)
            self.assertNotIn("Sætning", shown, size)
            self.assertEqual(shown.strip(), "Godt. Nu laver vi en lytteøvelse.", size)
            self.assertEqual([e for e in evs if e[0] == "listen"], [("listen", SENTENCE)], size)
            self.assertEqual([e for e in evs if e[0] == "signal"], [("signal", "listening", "2 of 5")], size)

    def test_fix_and_payload_removed(self):
        fix = '{"said": "et ny cykel", "correct": "en ny cykel", "why": "Cykel takes en."}'
        text = f'<fix>{fix}</fix>Fin cykel!\n```json\n{{"date": "2026-11-06"}}\n```\n⏳ **Skriver ned.**'
        for size in (1, 2, 5, len(text)):
            evs = run_filter(text, size)
            self.assertEqual("".join(e[1] for e in evs if e[0] == "text").strip(), "Fin cykel!")
            self.assertEqual([e for e in evs if e[0] == "fix"], [("fix", fix)])
            self.assertEqual([e for e in evs if e[0] == "payload"], [("payload", '{"date": "2026-11-06"}')])
            self.assertIn(("signal", "saving", ""), evs)

    def test_unclosed_listen_is_never_shown(self):
        evs = run_filter("Lyt: <listen>En hemmelig sætning", 4)
        self.assertNotIn("hemmelig", "".join(e[1] for e in evs if e[0] == "text"))
        self.assertIn(("listen", "En hemmelig sætning"), evs)

    def test_signal_kinds_and_plain_text_untouched(self):
        self.assertEqual(dansk_practice.classify_signal("\U0001f3a4 **Din tur.**")[1], "your_turn")
        self.assertEqual(dansk_practice.classify_signal("✅ **Færdig for i dag.**")[1], "done")
        self.assertEqual(dansk_practice.classify_signal(
            "\U0001f50a Samme sætning, langsommere. \U0001f3a4 **Prøv igen.**")[1], "replay")
        evs = run_filter("Hvad med <b>dig</b>? 3 < 4.\nJa.", 1)
        self.assertEqual("".join(e[1] for e in evs if e[0] == "text"), "Hvad med <b>dig</b>? 3 < 4.\nJa.")


class Fixes(helpers.TempCase):
    def test_parse_fix(self):
        self.assertEqual(dansk_practice.parse_fix('{"said": " a ", "correct": "b", "x": 1}'),
                         {"said": "a", "correct": "b"})
        for bad in ("not json", "[1]", '{"said": "a"}', '{"said": 3, "correct": "b"}'):
            self.assertIsNone(dansk_practice.parse_fix(bad), bad)

    def test_merge_adds_missing_fixes_once(self):
        fixes = [{"said": "et ny cykel", "correct": "en ny cykel", "why": "Cykel takes en."},
                 {"said": "a", "correct": "b", "pattern_id": "Bad Id!", "severity": "huge"}]
        p = {"errors": [{"pattern_id": "cykel_gender", "said": "et ny cykel", "correct": "en ny cykel"}]}
        out = dansk_practice.merge_fixes(p, fixes)
        self.assertEqual(len(out["errors"]), 2)
        added = out["errors"][1]
        self.assertTrue(dansk_db.PATTERN_ID.match(added["pattern_id"]), added)
        self.assertEqual((added["severity"], added["category"]), ("minor", "grammar"))
        self.assertEqual(dansk_practice.merge_fixes({}, fixes[:1])["errors"][0]["context"], "Cykel takes en.")


class Prompt(helpers.TempCase):
    def test_prompt_holds_rules_data_and_runner(self):
        due = {"first_session": False, "due_count": 1, "due_items": [{"id": "vocab_noegle"}],
               "error_patterns": [], "learner": {"level": "A2"}}
        p = dansk_practice.build_prompt("words", None, {"goal": "work"}, due,
                                        [{"headword": "nøgle", "gloss": "key"}], "2026-11-06")
        for want in ("# Dansk session rules", "<listen>", "<fix>", "```json", "vocab_noegle",
                     "- nøgle (key)", "asked you to choose the topic", "2026-11-06", "Learn new words"):
            self.assertIn(want, p)
        self.assertNotIn(chr(0x2014), p)
        self.assertEqual(dansk_practice.topic_ideas("work and meetings")[0], "Your working day")
        self.assertEqual(len(dansk_practice.topic_ideas("")), 3)


class Practice(ServerBase):
    def before_server(self):
        self._penv = {k: os.environ.get(k) for k in ("FAKE_TUTOR_SCENARIO", "FAKE_TUTOR_DELAY")}
        os.environ["DANISH_TUTOR_BACKEND"] = FAKE       # TempCase restores it afterwards
        os.environ.pop("FAKE_TUTOR_DELAY", None)
        os.environ.pop("FAKE_TUTOR_SCENARIO", None)

    def setUp(self):
        super().setUp()
        poll = mock.patch.object(dansk_app, "POLL_SECONDS", 2)    # shorter than the client timeout
        poll.start()
        self.addCleanup(poll.stop)
        self.seen = 0

    def tearDown(self):
        self.srv.api.practice.stop_all()
        for k, v in self._penv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def backend(self):
        return self.srv.api.practice.backend

    def start(self, mode="short", topic=None, scenario="normal"):
        self.backend().scenario = scenario
        body = {"mode": mode} if topic is None else {"mode": mode, "topic": topic}
        status, s = self.request("POST", "/api/practice/start", body)
        self.assertEqual(status, 200, s)
        self.seen = 0
        return s["id"]

    def until(self, sid, pred, timeout=20):
        got = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            status, r = self.request("GET", f"/api/practice/{sid}/events?after={self.seen}")
            self.assertEqual(status, 200, r)
            got += r["events"]
            if r["events"]:
                self.seen = r["events"][-1]["seq"]
            if pred(got, r["session"]):
                return got
        self.fail(f"timed out; events: {got}")

    @staticmethod
    def idle(evs, s):
        return s["state"] in ("waiting", "saved", "ended", "finished")

    def say(self, sid, text, via="typed"):
        status, body = self.request("POST", f"/api/practice/{sid}/message", {"text": text, "via": via})
        self.assertEqual(status, 200, body)
        return self.until(sid, self.idle)

    def test_full_flow_fix_listen_save_finish(self):
        sid = self.start(mode="words", topic="morgenmad")
        evs = self.until(sid, self.idle)
        shown = "".join(e["text"] for e in evs if e["type"] == "text")
        self.assertIn("Hej! Hvad har du lyst", shown)
        self.assertNotIn("Din tur", shown)
        self.assertIn(("your_turn", ""), [(e["signal"], e["detail"]) for e in evs if e["type"] == "signal"])
        system, msgs, effort = self.backend().calls[0]
        self.assertIn("The learner chose the topic: morgenmad", system)
        self.assertIn("vocab_noegle", system)
        self.assertEqual(effort, "low")

        evs = self.say(sid, "Jeg spiser ikke, fordi jeg har ikke tid", via="voice")
        fixes = [e for e in evs if e["type"] == "fix"]
        self.assertEqual([(f["said"], f["correct"]) for f in fixes],
                         [("fordi jeg har ikke tid", "fordi jeg ikke har tid")])
        shown = "".join(e["text"] for e in evs if e["type"] == "text")
        self.assertNotIn("<fix>", shown)
        self.assertTrue(shown.startswith("Nå, så du ikke har tid"))
        self.assertTrue(self.backend().calls[-1][1][-1]["content"].startswith("[app: 1 min in, voice]"))

        evs = self.say(sid, "Brød")
        shown = "".join(e["text"] for e in evs if e["type"] == "text")
        self.assertNotIn("nøglen", shown)              # the hidden sentence never reaches the chat
        self.assertEqual([e["sentence"] for e in evs if e["type"] == "listen"], [SENTENCE])

        self.say(sid, "Hvor er nøglen")
        status, _ = self.request("POST", f"/api/practice/{sid}/end")
        self.assertEqual(status, 200)
        evs = self.until(sid, lambda e, s: s["state"] == "finished")
        self.assertEqual(self.backend().calls[4][2], "medium")     # the wrap-up turn
        saved = [e for e in evs if e["type"] == "saved"]
        self.assertEqual(len(saved), 1, evs)
        self.assertTrue(saved[0]["line"].startswith("saved session-2026-11-06, 1 reviews, 1 new words, 1 errors"),
                        saved[0]["line"])
        shown = "".join(e["text"] for e in evs if e["type"] == "text")
        self.assertNotIn('"new_words"', shown)
        self.assertIn("Tak for snakken", shown)
        con = dansk_db.connect(self.db)
        try:
            w = dansk_db.find_word(con, "paraply")
            sess = dansk_db.get_session(con, "session-2026-11-06")
            err = dansk_db.get_item(con, "error_ikke_placement")
        finally:
            con.close()
        self.assertEqual((w["gloss"], w["forms"]), ("umbrella", "en paraply, paraplyen, paraplyer, paraplyerne"))
        self.assertEqual(sess["input_mode"], "mixed")
        self.assertEqual([e["said"] for e in sess["errors"]], ["fordi jeg har ikke tid"])   # from the fix
        self.assertEqual(err["due_date"], "2026-11-07")
        status, _ = self.request("POST", f"/api/practice/{sid}/message", {"text": "hej"})
        self.assertEqual(status, 409)

    def test_bad_payload_kept_and_retry_saves(self):
        sid = self.start(scenario="bad_payload")
        self.until(sid, self.idle)
        self.request("POST", f"/api/practice/{sid}/end")
        evs = self.until(sid, lambda e, s: any(x["type"] == "save_error" for x in e) and self.idle(e, s))
        err = next(e for e in evs if e["type"] == "save_error")
        self.assertIn("  size: must be small or large", err["problems"])
        self.assertTrue(Path(err["path"]).is_file())
        self.addCleanup(lambda: Path(err["path"]).unlink(missing_ok=True))
        con = dansk_db.connect(self.db)
        self.assertIsNone(dansk_db.find_word(con, "paraply"))      # nothing written
        con.close()
        status, _ = self.request("POST", f"/api/practice/{sid}/retry")
        self.assertEqual(status, 200)
        self.until(sid, lambda e, s: any(x["type"] == "saved" for x in e))
        con = dansk_db.connect(self.db)
        self.assertIsNotNone(dansk_db.find_word(con, "paraply"))
        con.close()

    def test_missing_payload_reported(self):
        sid = self.start(scenario="no_payload")
        self.until(sid, self.idle)
        self.request("POST", f"/api/practice/{sid}/end")
        evs = self.until(sid, lambda e, s: any(x["type"] == "save_error" for x in e))
        self.assertIn("no payload", next(e for e in evs if e["type"] == "save_error")["problems"][0])

    def test_refusal_discards_turn_and_line_can_be_resent(self):
        sid = self.start(scenario="refusal")
        self.until(sid, self.idle)
        evs = self.say(sid, "Noget")
        types = [e["type"] for e in evs]
        self.assertIn("discard", types)
        err = next(e for e in evs if e["type"] == "error")
        self.assertEqual(err["kind"], "refusal")
        hist = self.srv.api.practice.current.history
        self.assertEqual([m["role"] for m in hist], ["user", "assistant"])   # refused turn dropped
        self.backend().scenario = "normal"
        self.say(sid, "Noget andet")
        self.assertEqual(len(self.srv.api.practice.current.history), 4)

    def test_stop_and_one_session_at_a_time(self):
        self.backend().delay = 0.05
        sid = self.start()
        status, body = self.request("POST", "/api/practice/start", {"mode": "chat"})
        self.assertEqual(status, 409, body)
        status, _ = self.request("POST", f"/api/practice/{sid}/stop")
        self.assertEqual(status, 200)
        s = self.srv.api.practice.current
        self.assertEqual(s.state, "ended")
        self.assertTrue(s.cancelled)
        self.start()                                       # a new one may start now
        self.srv.api.practice.stop_all()                   # what the server does on exit
        self.assertEqual(self.srv.api.practice.current.state, "ended")

    def test_bad_requests(self):
        for b in ({"mode": "nope"}, {"mode": "chat", "x": 1}, {"mode": "words", "topic": 3}, [1]):
            status, _ = self.request("POST", "/api/practice/start", b)
            self.assertEqual(status, 400, b)
        status, _ = self.request("GET", "/api/practice/0123456789abcdef/events")
        self.assertEqual(status, 404)
        self.backend().delay = 0.05
        sid = self.start()
        status, _ = self.request("POST", f"/api/practice/{sid}/message", {"text": "hej"})
        self.assertEqual(status, 409)                      # the tutor is still replying
        for b in ({"text": ""}, {"text": "x", "via": "phone"}, {"text": "x" * 5000}):
            status, _ = self.request("POST", f"/api/practice/{sid}/message", b)
            self.assertEqual(status, 400, b)

    def test_status_without_key(self):
        self.backend().scenario = "no_key"
        status, st = self.request("GET", "/api/practice")
        self.assertEqual((status, st["available"], st["problem"]), (200, False, "key"))
        self.assertIn("DANISH_TUTOR_ANTHROPIC_KEY", st["message"])
        status, body = self.request("POST", "/api/practice/start", {"mode": "chat"})
        self.assertEqual(status, 409)
        self.assertEqual(len(st["topics"]), 3)


class RealBackendWithoutSdk(helpers.TempCase):
    def test_missing_sdk_reports_pip_install(self):
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            st = dansk_tutor.AnthropicBackend().status()
        self.assertEqual((st["ready"], st["problem"]), (False, "sdk"))
        self.assertIn("pip install anthropic", st["message"])

    def test_echo_content_after_fallback(self):
        blocks = [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "a"},
                  {"type": "fallback"}, {"type": "thinking", "thinking": ""}, {"type": "text", "text": "b"}]
        self.assertEqual([b["type"] for b in dansk_tutor.echo_content(blocks)],
                         ["text", "fallback", "thinking", "text"])
        self.assertEqual(dansk_tutor.echo_content(blocks[:2]), blocks[:2])
