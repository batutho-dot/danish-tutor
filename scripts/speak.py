#!/usr/bin/env python3
"""Speak one Danish sentence aloud without showing it, for the hidden listening drill.

    python speak.py [--rate 150] [--voice auto|local-daemon|system] "Danish sentence here"
    python speak.py --stop

Voices, tried in this order with --voice auto (the default; the settings key `voice` sets it
too, --voice wins):

  local-daemon  a local text-to-speech daemon that speaks this small JSON protocol, for
                example claude-local-voice. One JSON object per connection:
                {"runs": [{"lang": "da", "text": "..."}]} speaks (a new request cancels what
                is playing), {"stop": true} cuts playback. Windows: TCP on 127.0.0.1, port
                CLV_PORT (default 47821). macOS and Linux: the Unix socket CLV_SOCKET (default
                CLV_HOME/voice.sock, CLV_HOME default ~/.claude-local-voice). The daemon sets
                its own pace, so --rate does not apply to it.
  system        macOS `say` with "Sara (Enhanced)", or else any installed voice listed as
                da_DK by `say -v '?'`. Windows: PowerShell with System.Speech, using an
                installed voice whose culture starts with "da". Linux: `espeak-ng -v da`.

--rate is in words per minute. `say` and espeak-ng take words per minute directly. Windows
SAPI takes a rate from -10 to 10 instead; we map it with an approximation of our own, not a
measured one: rate = round((wpm - 150) / 15), clamped to -10..10, so 150 wpm is SAPI's
normal speed 0, 130 is -1 and 180 is 2.

The sentence never reaches a shell: it goes to the speech program on standard input
(say, espeak-ng), in an environment variable (PowerShell) or in the JSON sent to the daemon,
with argument lists only. It is never printed or logged.

Exit codes: 0 spoken (or stopped), 1 bad arguments, 3 no Danish voice found, 4 the speech
program failed. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PREFERRED_MAC_VOICE = "Sara (Enhanced)"
DAEMON_PORT = 47821
DAEMON_TIMEOUT = 1.5
VOICES = ("auto", "local-daemon", "system")

HELP_VOICE = {
    "Darwin": "no Danish voice found: open System Settings > Accessibility > Spoken Content > "
              "System voice > Manage Voices, and download a Danish voice",
    "Windows": "no Danish voice found: open Settings > Time & language > Language & region, "
               "add Danish with the speech option, then try again",
    "Linux": "no Danish voice found: install espeak-ng (it includes Danish, voice da)",
}

# Fixed scripts; the text and the rate arrive in environment variables, never in the script.
PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'da*' } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = [int]$env:DANISH_TUTOR_SAPI_RATE
$s.Speak($env:DANISH_TUTOR_TEXT)
exit 0
"""
PS_HAS_VOICE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'da*' } | Select-Object -First 1
if (-not $v) { exit 3 }
exit 0
"""


def sapi_rate(wpm: int) -> int:
    """Approximate words-per-minute to SAPI rate (-10..10). Our approximation, not measured."""
    return max(-10, min(10, round((wpm - 150) / 15)))


# ---------------------------------------------------------------- local daemon

def daemon_address() -> tuple[int, object]:
    """(family, address) of the local voice daemon: TCP on Windows, a Unix socket elsewhere."""
    if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
        try:
            port = int(os.environ.get("CLV_PORT") or DAEMON_PORT)
        except ValueError:
            port = DAEMON_PORT
        return socket.AF_INET, ("127.0.0.1", port)
    sock = os.environ.get("CLV_SOCKET")
    if not sock:
        home = os.environ.get("CLV_HOME") or str(Path.home() / ".claude-local-voice")
        sock = str(Path(home).expanduser() / "voice.sock")
    return socket.AF_UNIX, sock


def daemon_send(obj: dict) -> bool:
    """Send one JSON request to the daemon. True if it was delivered."""
    family, addr = daemon_address()
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(DAEMON_TIMEOUT)
            s.connect(addr)
            s.sendall(data)
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        return True
    except OSError:
        return False


def daemon_up() -> bool:
    """Whether something accepts connections at the daemon's address (connects, sends
    nothing, closes)."""
    family, addr = daemon_address()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(DAEMON_TIMEOUT)
            s.connect(addr)
        return True
    except OSError:
        return False


def speak_daemon(text: str) -> bool:
    return daemon_send({"runs": [{"lang": "da", "text": text}]})


def stop_daemon() -> bool:
    return daemon_send({"stop": True})


# ---------------------------------------------------------------- system voice

def mac_voice() -> str | None:
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    except OSError:
        return None
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[_-][A-Z]{2})\b", line)
        if m:
            voices.append((m.group(1).strip(), m.group(2)))
    if any(name == PREFERRED_MAC_VOICE for name, _ in voices):
        return PREFERRED_MAC_VOICE
    for name, locale in voices:
        if locale.replace("-", "_") == "da_DK":
            return name
    return None


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def system_voice_available() -> bool:
    system = platform.system()
    if system == "Darwin":
        return mac_voice() is not None
    if system == "Windows":
        ps = _powershell()
        if not ps:
            return False
        try:
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", PS_HAS_VOICE],
                               capture_output=True, text=True, errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0
    return shutil.which("espeak-ng") is not None


def system_command(text: str, wpm: int) -> tuple[list[str], dict | None, str | None] | int:
    """The argument list, environment and standard input that speak `text` with the system
    voice, or an exit code (3 no voice, 4 no speech program)."""
    system = platform.system()
    if system == "Darwin":
        voice = mac_voice()
        if not voice:
            return 3
        return ["say", "-v", voice, "-r", str(wpm)], None, text
    if system == "Windows":
        ps = _powershell()
        if not ps:
            return 4
        env = dict(os.environ, DANISH_TUTOR_TEXT=text, DANISH_TUTOR_SAPI_RATE=str(sapi_rate(wpm)))
        return [ps, "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT], env, None
    if shutil.which("espeak-ng"):
        return ["espeak-ng", "-v", "da", "-s", str(wpm), "--stdin"], None, text
    return 3


def speak_system(text: str, wpm: int) -> int:
    cmd = system_command(text, wpm)
    if isinstance(cmd, int):
        return cmd
    args, env, stdin = cmd
    try:
        r = subprocess.run(args, env=env, input=stdin, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return 4
    if r.returncode == 3 and platform.system() == "Windows":
        return 3
    return 0 if r.returncode == 0 else 4


# ---------------------------------------------------------------- choosing

def configured_voice() -> str:
    """The `voice` setting from the settings file, or auto."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dansk_db
        v = str(dansk_db.load_config().get("voice") or "auto")
    except Exception:
        v = "auto"
    return v if v in VOICES else "auto"


def available(voice: str = "auto") -> str:
    """Which voice would speak: "local", "system" or "none"."""
    if voice in ("auto", "local-daemon") and daemon_up():
        return "local"
    if voice in ("auto", "system") and system_voice_available():
        return "system"
    return "none"


def speak(text: str, wpm: int, voice: str = "auto") -> int:
    """Speak with the chosen voice. Returns an exit code; prints nothing."""
    if voice in ("auto", "local-daemon") and speak_daemon(text):
        return 0
    if voice == "local-daemon":
        return 3
    return speak_system(text, wpm)


def help_line() -> str:
    return HELP_VOICE.get(platform.system(), HELP_VOICE["Linux"]) + (
        "; or run a local text-to-speech daemon (see docs/details.md, speak.py)")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Speak one Danish sentence (hidden listening drill)")
    ap.add_argument("--rate", type=int, default=150, help="words per minute (default 150)")
    ap.add_argument("--voice", choices=VOICES, help="auto (default), local-daemon or system")
    ap.add_argument("--stop", action="store_true", help="stop what the local daemon is playing")
    ap.add_argument("text", nargs="?", default="", help="the Danish sentence")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    if a.stop:
        return 0 if stop_daemon() else 4
    if not a.text.strip() or not 50 <= a.rate <= 400:
        print("give a non-empty sentence and a --rate from 50 to 400")
        return 1
    code = speak(a.text, a.rate, a.voice or configured_voice())
    if code == 3:
        print(help_line())
    elif code == 4:
        print("speech failed: the speech program did not finish")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
