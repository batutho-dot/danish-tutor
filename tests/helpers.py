"""Shared test setup: import paths, a temp folder per test, and isolation from real settings."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
for sub in ("scripts", "dashboard"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

EXAMPLE = ROOT / "example-data"


class TempCase(unittest.TestCase):
    """Each test gets its own temp folder; settings and database env vars point inside it,
    so no test can read or write a real learner's files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._env = {k: os.environ.get(k) for k in
                     ("DANISH_TUTOR_CONFIG", "DANISH_TUTOR_DB", "DANSK_DATA_DIR", "DANSK_WORDS_DIR")}
        os.environ["DANISH_TUTOR_CONFIG"] = str(self.tmp / "config.json")
        os.environ["DANISH_TUTOR_DB"] = str(self.tmp / "default.db")
        os.environ.pop("DANSK_DATA_DIR", None)
        os.environ.pop("DANSK_WORDS_DIR", None)
        self.db = self.tmp / "dansk.db"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


def run_main(main, argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()
