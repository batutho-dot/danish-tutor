"""The real AnthropicBackend with the real `anthropic` SDK, against a local stub HTTP server
(ANTHROPIC_BASE_URL points at it): the exact request the SDK sends, the streamed reply, a
refusal, and the error mapping. Skipped when the SDK is not installed. Nothing leaves the
machine; the key is an invented test value."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import helpers
import dansk_tutor

try:
    import anthropic  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

TEST_KEY = "test-key-not-real"


def sse(stop_reason="end_turn", text="Hej med dig"):
    msg = {"id": "msg_test", "type": "message", "role": "assistant", "model": dansk_tutor.MODEL,
           "content": [], "stop_reason": None, "stop_sequence": None,
           "usage": {"input_tokens": 5, "output_tokens": 1}}
    events = [("message_start", {"type": "message_start", "message": msg}),
              ("content_block_start", {"type": "content_block_start", "index": 0,
                                       "content_block": {"type": "text", "text": ""}})]
    for part in (text[:4], text[4:]):
        events.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta", "text": part}}))
    events += [("content_block_stop", {"type": "content_block_stop", "index": 0}),
               ("message_delta", {"type": "message_delta",
                                  "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                  "usage": {"output_tokens": 4}}),
               ("message_stop", {"type": "message_stop"})]
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.server.requests.append((self.path, dict(self.headers), json.loads(self.rfile.read(n))))
        mode = self.server.mode
        if mode in (401, 400):
            body = json.dumps({"type": "error", "error": {"type": "x", "message": "stub"}}).encode()
            self.send_response(mode)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = sse("refusal" if mode == "refusal" else "end_turn")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(HAVE_SDK, "the anthropic SDK is not installed (pip install anthropic)")
class RealSdkAgainstStub(helpers.TempCase):
    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        self.srv.requests, self.srv.mode = [], "ok"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self._env = {k: os.environ.get(k) for k in
                     ("ANTHROPIC_BASE_URL", "DANISH_TUTOR_ANTHROPIC_KEY", "ANTHROPIC_API_KEY")}
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.srv.server_address[1]}"
        os.environ["DANISH_TUTOR_ANTHROPIC_KEY"] = TEST_KEY
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def call(self):
        got = []
        b = dansk_tutor.AnthropicBackend()
        content = b.stream_reply("SYSTEM", [{"role": "user", "content": "hej"}], "low",
                                 got.append, lambda: False)
        return b, got, content

    def test_request_shape_and_streamed_reply(self):
        b, got, content = self.call()
        self.assertEqual(b.status()["ready"], True)
        self.assertEqual("".join(got), "Hej med dig")
        self.assertEqual(content, [{"type": "text", "text": "Hej med dig", "citations": None}]
                         if "citations" in content[0] else [{"type": "text", "text": "Hej med dig"}])
        path, headers, body = self.srv.requests[0]
        self.assertTrue(path.startswith("/v1/messages"), path)
        h = {k.lower(): v for k, v in headers.items()}
        # the dedicated variable is used (sent as x-api-key, or as a bearer token by newer SDKs)
        self.assertIn(TEST_KEY, (h.get("x-api-key"), h.get("authorization", "").removeprefix("Bearer ")))
        self.assertIn(dansk_tutor.FALLBACK_BETA, h.get("anthropic-beta", ""))
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertTrue(body["stream"])
        self.assertEqual(body["system"], [{"type": "text", "text": "SYSTEM",
                                           "cache_control": {"type": "ephemeral"}}])
        self.assertNotIn("thinking", body)

    def test_refusal_raises(self):
        self.srv.mode = "refusal"
        with self.assertRaises(dansk_tutor.TutorError) as cm:
            self.call()
        self.assertEqual(cm.exception.kind, "refusal")

    def test_errors_mapped_without_the_key(self):
        for mode, kind in ((401, "key"), (400, "api")):
            self.srv.mode = mode
            with self.assertRaises(dansk_tutor.TutorError) as cm:
                self.call()
            self.assertEqual(cm.exception.kind, kind, mode)
            self.assertNotIn(TEST_KEY, cm.exception.message)
