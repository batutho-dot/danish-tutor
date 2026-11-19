"""The installable package: data folder lookup, packaged data paths, history caching and the
optional piper voice (with piper itself faked, so the tests never download or play audio)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import helpers

import dansk_app  # noqa: E402
import dansk_db  # noqa: E402
import dansk_practice  # noqa: E402
import dansk_tutor  # noqa: E402
import speak  # noqa: E402


class DataDir(helpers.TempCase):
    def test_env_wins(self):
        self.assertEqual(dansk_db.data_dir(), self.tmp / "home")

    def test_plugin_folder_when_it_exists_else_dot_folder(self):
        os.environ.pop("DANISH_TUTOR_HOME")
        os.environ.pop("DANISH_TUTOR_DB")
        os.environ.pop("DANISH_TUTOR_CONFIG")
        with mock.patch.object(Path, "home", return_value=self.tmp):
            self.assertEqual(dansk_db.data_dir(), self.tmp / ".danish-tutor")
            self.assertEqual(dansk_db.db_path(), self.tmp / ".danish-tutor" / "dansk.db")
            (self.tmp / ".claude" / "danish-tutor").mkdir(parents=True)
            self.assertEqual(dansk_db.data_dir(), self.tmp / ".claude" / "danish-tutor")
            self.assertEqual(dansk_db.config_path(),
                             self.tmp / ".claude" / "danish-tutor" / "config.json")


class PackagedFiles(unittest.TestCase):
    def test_repo_paths_exist(self):
        self.assertTrue((dansk_app.DIST / "index.html").is_file())
        self.assertTrue((dansk_app.EXAMPLE / "spaced-repetition.json").is_file())
        self.assertTrue(dansk_practice.RULES.is_file())


class CacheHistory(unittest.TestCase):
    def test_last_block_gets_breakpoint_without_changing_input(self):
        msgs = [{"role": "user", "content": "hej"},
                {"role": "assistant", "content": [{"type": "text", "text": "Hej!"}]},
                {"role": "user", "content": [{"type": "text", "text": "a"},
                                             {"type": "text", "text": "b"}]}]
        before = repr(msgs)
        out = dansk_tutor.cache_history(msgs)
        self.assertEqual(repr(msgs), before)
        self.assertEqual(out[-1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", out[-1]["content"][0])
        self.assertEqual(out[:2], msgs[:2])

    def test_string_content_and_empty(self):
        out = dansk_tutor.cache_history([{"role": "user", "content": "hej"}])
        self.assertEqual(out[0]["content"],
                         [{"type": "text", "text": "hej", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(dansk_tutor.cache_history([]), [])


class Piper(helpers.TempCase):
    def test_not_installed_means_not_ready(self):
        with mock.patch.object(speak, "piper_installed", return_value=False):
            self.assertFalse(speak.piper_ready())
            self.assertFalse(speak.fetch_piper_voice())

    def test_voice_file_lives_in_data_folder(self):
        self.assertEqual(speak.piper_model(),
                         self.tmp / "home" / "voices" / f"{speak.PIPER_VOICE}.onnx")

    def test_ready_needs_both_files(self):
        m = speak.piper_model()
        m.parent.mkdir(parents=True)
        m.write_bytes(b"x")
        with mock.patch.object(speak, "piper_installed", return_value=True):
            self.assertFalse(speak.piper_ready())
            m.with_suffix(".onnx.json").write_text("{}")
            self.assertTrue(speak.piper_ready())

    def test_available_order(self):
        with mock.patch.object(speak, "piper_ready", return_value=True), \
             mock.patch.object(speak, "system_voice_available", return_value=True):
            self.assertEqual(speak.available("auto"), "piper")
            self.assertEqual(speak.available("system"), "system")
        with mock.patch.object(speak, "piper_ready", return_value=False):
            self.assertEqual(speak.available("piper"), "none")

    def test_player_command_windows(self):
        with mock.patch.object(speak.platform, "system", return_value="Windows"):
            cmd = speak.player_command(Path("a.wav"))
        self.assertEqual(cmd[-1], "a.wav")
        self.assertIn("winsound", cmd[2])


class PiperApi(helpers.TempCase):
    def test_app_speaks_with_piper_and_stops_it(self):
        db = self.tmp / "t.db"
        dansk_app.create_db(db)
        api = dansk_app.Api(db, None, False, {})

        def fake_wav(text, out, slow=False):
            Path(out).write_bytes(b"RIFF")
            return True

        with mock.patch.object(speak, "piper_ready", return_value=True), \
             mock.patch.object(speak, "piper_wav", side_effect=fake_wav), \
             mock.patch.object(speak, "player_command",
                               return_value=[helpers.sys.executable, "-c",
                                             "import time; time.sleep(30)"]):
            self.assertEqual(api.voice(fresh=True)["voice"], "piper")
            self.assertEqual(api.speak({"text": "Hej"}), {"voice": "piper"})
            proc = api.speech_proc
            self.assertIsNone(proc.poll())
            api.speak_stop()
            proc.wait(10)
            self.assertIsNotNone(proc.poll())


if __name__ == "__main__":
    unittest.main()
