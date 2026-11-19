#!/usr/bin/env python3
"""Speak one Danish sentence aloud without showing it, for the hidden listening drill.

    python speak.py --rate 150 "Danish sentence here"

  macOS    `say` with "Sara (Enhanced)", or else any installed voice listed as da_DK by
           `say -v '?'`.
  Windows  PowerShell with System.Speech, using an installed voice whose culture starts
           with "da".
  Linux    `espeak-ng -v da`, if it is installed.

--rate is in words per minute. `say` and espeak-ng take words per minute directly. Windows
SAPI takes a rate from -10 to 10 instead; we map it with an approximation of our own, not a
measured one: rate = round((wpm - 150) / 15), clamped to -10..10, so 150 wpm is SAPI's
normal speed 0, 130 is -1 and 180 is 2.

The sentence never reaches a shell: it goes to the speech program on standard input
(say, espeak-ng) or in an environment variable (PowerShell), with argument lists only.

Exit codes: 0 spoken, 1 bad arguments, 3 no Danish voice found, 4 the speech program failed.
Standard library only.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys

PREFERRED_MAC_VOICE = "Sara (Enhanced)"

HELP_VOICE = {
    "Darwin": "no Danish voice found: open System Settings > Accessibility > Spoken Content > "
              "System voice > Manage Voices, and download a Danish voice",
    "Windows": "no Danish voice found: open Settings > Time & language > Language & region, "
               "add Danish with the speech option, then try again",
    "Linux": "no Danish voice found: install espeak-ng (it includes Danish, voice da)",
}

# Fixed script; the text and the rate arrive in environment variables, never in the script.
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


def sapi_rate(wpm: int) -> int:
    """Approximate words-per-minute to SAPI rate (-10..10). Our approximation, not measured."""
    return max(-10, min(10, round((wpm - 150) / 15)))


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


def speak(text: str, wpm: int) -> int:
    system = platform.system()
    if system == "Darwin":
        voice = mac_voice()
        if not voice:
            print(HELP_VOICE["Darwin"])
            return 3
        r = subprocess.run(["say", "-v", voice, "-r", str(wpm)], input=text, text=True,
                           encoding="utf-8")
        return 0 if r.returncode == 0 else 4
    if system == "Windows":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            print("PowerShell not found, so Windows speech cannot be used")
            return 4
        env = dict(os.environ, DANISH_TUTOR_TEXT=text, DANISH_TUTOR_SAPI_RATE=str(sapi_rate(wpm)))
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
                           env=env, capture_output=True, text=True, errors="replace")
        if r.returncode == 3:
            print(HELP_VOICE["Windows"])
            return 3
        if r.returncode != 0:
            print(f"speech failed: {(r.stderr or r.stdout).strip()[:300]}")
            return 4
        return 0
    if shutil.which("espeak-ng"):
        r = subprocess.run(["espeak-ng", "-v", "da", "-s", str(wpm), "--stdin"], input=text,
                           text=True, encoding="utf-8")
        return 0 if r.returncode == 0 else 4
    print(HELP_VOICE["Linux"])
    return 3


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Speak one Danish sentence (hidden listening drill)")
    ap.add_argument("--rate", type=int, default=150, help="words per minute (default 150)")
    ap.add_argument("text", help="the Danish sentence")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    if not a.text.strip() or not 50 <= a.rate <= 400:
        print("give a non-empty sentence and a --rate from 50 to 400")
        return 1
    return speak(a.text, a.rate)


if __name__ == "__main__":
    raise SystemExit(main())
