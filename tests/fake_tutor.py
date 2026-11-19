"""A scripted stand-in for the Anthropic API tutor (scripts/dansk_tutor.py), for the tests,
verify.py and screenshots: set DANISH_TUTOR_BACKEND to this file. No network, no key.

Replies are canned Danish lines, streamed three characters at a time so every marker
(<listen>, <fix>, the ```json payload, the signal lines) is split across chunks.
FAKE_TUTOR_SCENARIO: normal (default), bad_payload (the first payload is invalid, the retry
is valid), no_payload, refusal (the second turn is refused mid-stream), no_key (status says
there is no key). FAKE_TUTOR_DELAY: seconds between chunks (default 0).
All Danish here is invented example text.
"""
import json
import os
import re
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dansk_tutor  # noqa: E402

MIC = "\U0001f3a4 **Din tur.**"
OPENING = "Hej! Hvad har du lyst til at snakke om i dag?\n\n" + MIC
FIX = {"said": "fordi jeg har ikke tid", "correct": "fordi jeg ikke har tid",
       "why": "After fordi, ikke comes before the verb.", "category": "word_order",
       "pattern_id": "ikke_placement", "severity": "moderate"}
CHAT = ("<fix>" + json.dumps(FIX, ensure_ascii=False) + "</fix>"
        "Nå, så du ikke har tid til morgenmad? Hvad spiser du så, når du har travlt?\n\n" + MIC)
LISTEN = ("Godt. Nu en lille lytteøvelse.\n\n<listen>Hvor har du lagt nøglen?</listen>\n\n"
          "\U0001f50a Sætning 1 af 1. \U0001f3a4 **Hvad hørte du?**")
FOLLOW = "Fint! Hvad skal du lave i weekenden?\n\n" + MIC
CLOSING = "Tak for snakken. Vi ses i morgen!\n\n✅ **Færdig for i dag.**"


def payload(day, minutes, mode, bad=False):
    return {
        "date": day, "duration_minutes": minutes, "size": "huge" if bad else "small",
        "input_mode": mode, "topic": "morgenmad", "summary": "Invented test chat about breakfast.",
        "skills": ["speaking", "listening"],
        "reviews": [{"item_id": "vocab_noegle", "quality": 4}],
        "new_words": [{"headword": "paraply", "kind": "word", "pos": "noun",
                       "gender": "fælleskøn", "level": "A2",
                       "forms": "en paraply, paraplyen, paraplyer, paraplyerne",
                       "definition": "Den bruger man, når det regner.", "gloss": "umbrella",
                       "example": "Jeg har glemt min paraply.", "category": "weather"}],
        "listening": [{"sentence": "Hvor har du lagt nøglen?", "result": "gist_only"}],
    }


def wrap_up(text, bad):
    day = (re.search(r"date (\d{4}-\d{2}-\d{2})", text) or [None, "2026-11-06"])[1]
    minutes = int((re.search(r"duration_minutes (\d+)", text) or [None, "5"])[1])
    mode = (re.search(r"input_mode (\w+)", text) or [None, "typed"])[1]
    body = json.dumps(payload(day, minutes, mode, bad), ensure_ascii=False, indent=1)
    return ("Godt gået! You kept the chat going in Danish the whole time. Watch where ikke goes "
            f"after fordi.\n\n```json\n{body}\n```\n\n⏳ **Skriver ned. Du behøver ikke sige noget.**")


class Backend:
    def __init__(self):
        self.scenario = os.environ.get("FAKE_TUTOR_SCENARIO", "normal")
        self.delay = float(os.environ.get("FAKE_TUTOR_DELAY", "0") or 0)
        self.calls = []                       # (system, messages, effort) per turn
        self.paid = False

    def status(self):
        if self.scenario == "no_key":
            return {"ready": False, "problem": "key", "message": dansk_tutor.NO_KEY,
                    "model": dansk_tutor.MODEL}
        return {"ready": True, "problem": None, "message": "", "model": dansk_tutor.MODEL}

    def reply_for(self, messages):
        text = messages[-1]["content"]
        turn = sum(1 for m in messages if m["role"] == "user")
        if "The session was saved" in text:
            return CLOSING
        if "pressed End session" in text:
            if self.scenario == "no_payload":
                return "Tak for i dag.\n\n⏳ **Skriver ned. Du behøver ikke sige noget.**"
            bad = self.scenario == "bad_payload" and not self.paid
            self.paid = True
            return wrap_up(text, bad)
        if "payload was not saved" in text:
            return wrap_up(text, False)
        if turn == 1:
            return OPENING
        if "har ikke" in text:
            return CHAT
        if turn <= 3:
            return LISTEN
        return FOLLOW

    def stream_reply(self, system, messages, effort, on_text, cancelled):
        self.calls.append((system, [dict(m) for m in messages], effort))
        text = self.reply_for(messages)
        turn = sum(1 for m in messages if m["role"] == "user")
        for i in range(0, len(text), 3):
            if cancelled():
                raise dansk_tutor.TutorError("cancelled", "The session was stopped.")
            if self.scenario == "refusal" and turn == 2 and i > 10:
                raise dansk_tutor.TutorError("refusal", "The tutor could not answer that line. "
                                                        "Try saying it another way.")
            on_text(text[i:i + 3])
            if self.delay:
                time.sleep(self.delay)
        return [{"type": "text", "text": text}]
