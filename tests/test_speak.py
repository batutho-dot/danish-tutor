"""speak.py and the app's voice endpoints against a FAKE voice daemon: a TCP server on a random
port (CLV_PORT) on Windows, a temporary Unix socket (CLV_SOCKET) elsewhere. The real daemon
and the real system voice are never used."""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
from pathlib import Path
from unittest import mock

import helpers
import speak
from test_app import ServerBase

SECRET = "En hemmelig sætning om nøglen."


class FakeDaemon:
    """Accepts connections and records each request's JSON (one object per connection)."""

    def __init__(self):
        if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.bind(("127.0.0.1", 0))
            os.environ["CLV_PORT"] = str(self.sock.getsockname()[1])
        else:
            self._dir = tempfile.mkdtemp(prefix="clv-")
            path = os.path.join(self._dir, "v.sock")
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.bind(path)
            os.environ["CLV_SOCKET"] = path
        self.sock.listen(5)
        self.got: list = []
        self.done = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                data = b""
                while chunk := c.recv(4096):
                    data += chunk
            if data:
                self.got.append(json.loads(data.decode("utf-8")))
                self.done.set()

    def wait(self):
        self.done.wait(5)
        self.done.clear()

    def close(self):
        self.sock.close()


class Speak(helpers.TempCase):
    def test_daemon_receives_exact_json_and_nothing_printed(self):
        d = FakeDaemon()
        self.addCleanup(d.close)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = speak.main(["--voice", "local-daemon", SECRET])
        d.wait()
        self.assertEqual(code, 0)
        self.assertEqual(d.got, [{"runs": [{"lang": "da", "text": SECRET}]}])
        self.assertNotIn("hemmelig", buf.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(speak.main(["--stop"]), 0)
        d.wait()
        self.assertEqual(d.got[-1], {"stop": True})
        self.assertEqual(speak.available("local-daemon"), "local")

    def test_no_daemon_falls_back_to_system(self):
        with mock.patch.object(speak, "speak_system", return_value=0) as sys_voice:
            self.assertEqual(speak.speak(SECRET, 150, "auto"), 0)
        sys_voice.assert_called_once_with(SECRET, 150)
        with mock.patch.object(speak, "speak_system", return_value=3):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = speak.main(["--voice", "auto", SECRET])
        self.assertEqual(code, 3)
        self.assertIn("no Danish voice", buf.getvalue())
        self.assertNotIn("hemmelig", buf.getvalue())

    def test_daemon_only_does_not_use_system(self):
        with mock.patch.object(speak, "speak_system") as sys_voice:
            self.assertEqual(speak.speak(SECRET, 150, "local-daemon"), 3)
        sys_voice.assert_not_called()
        with mock.patch.object(speak, "system_voice_available", return_value=False):
            self.assertEqual(speak.available("auto"), "none")

    def test_config_voice_setting(self):
        Path(os.environ["DANISH_TUTOR_CONFIG"]).write_text('{"voice": "system"}', encoding="utf-8")
        self.assertEqual(speak.configured_voice(), "system")
        Path(os.environ["DANISH_TUTOR_CONFIG"]).write_text('{"voice": "loud"}', encoding="utf-8")
        self.assertEqual(speak.configured_voice(), "auto")

    def test_sapi_rate(self):
        self.assertEqual([speak.sapi_rate(w) for w in (150, 130, 180, 400, 50)], [0, -1, 2, 10, -7])


class VoiceApi(ServerBase):
    def test_speak_through_daemon(self):
        d = FakeDaemon()
        self.addCleanup(d.close)
        status, v = self.request("GET", "/api/voice?fresh=1")
        self.assertEqual((status, v["voice"], v["label"]), (200, "local", "Local voice"))
        status, r = self.request("POST", "/api/speak", {"text": SECRET})
        d.wait()
        self.assertEqual((status, r), (200, {"voice": "local"}))
        self.assertEqual(d.got[-1], {"runs": [{"lang": "da", "text": SECRET}]})
        status, _ = self.request("POST", "/api/speak/stop")
        d.wait()
        self.assertEqual(d.got[-1], {"stop": True})

    def test_no_voice_is_503(self):
        with mock.patch.object(speak, "system_voice_available", return_value=False):
            status, v = self.request("GET", "/api/voice?fresh=1")
            self.assertEqual(v["voice"], "none")
            status, body = self.request("POST", "/api/speak", {"text": SECRET})
            self.assertEqual(status, 503)
            self.assertNotIn("hemmelig", json.dumps(body))

    def test_bad_speak_requests(self):
        for b in ({}, {"text": ""}, {"text": "x" * 2000}, {"text": "hej", "voice": "x"}, [1]):
            status, _ = self.request("POST", "/api/speak", b)
            self.assertEqual(status, 400, b)
        status, _ = self.request("POST", "/api/speak", {"text": "hej"}, token=False)
        self.assertEqual(status, 403)
