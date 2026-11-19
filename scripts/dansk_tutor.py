#!/usr/bin/env python3
"""The tutor's brain for the app's Practice page: the Anthropic API through the official
Python SDK (`pip install anthropic`, the plugin's only non-stdlib dependency).

Credentials: the environment variable DANISH_TUTOR_ANTHROPIC_KEY first, passed explicitly as
`anthropic.Anthropic(api_key=...)` (a dedicated variable, so a global ANTHROPIC_API_KEY that
would change how Claude Code itself bills is not needed). Without it, `anthropic.Anthropic()`
with no arguments, so the SDK finds ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an
`ant auth login` profile by itself. This module never asks for, stores, logs or shows a key,
and never prints request headers.

Model claude-sonnet-5-5, streamed with `client.beta.messages.stream` so the server-side
refusal fallback can be switched on (`fallbacks="default"`, beta
server-side-fallback-2026-07-01). Effort is "low" for conversational turns and "medium" for
the end-of-session payload. The system prompt is one cached block (it is the same for every
turn of a session). `stop_reason` is checked before the reply is used: a refusal discards
the turn.

A backend is any object with `status() -> dict` and
`stream_reply(system, messages, effort, on_text, cancelled) -> list[dict]` (the assistant
content blocks to keep in the history); tests use a fake one. Standard library only apart
from the lazy `import anthropic`.
"""
from __future__ import annotations

MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000

NO_SDK = "The Anthropic Python SDK is not installed. Run: pip install anthropic"
KEY_VAR = "DANISH_TUTOR_ANTHROPIC_KEY"
NO_KEY = ("No Anthropic API credentials found. Set the environment variable "
          "DANISH_TUTOR_ANTHROPIC_KEY to a key from console.anthropic.com (or set "
          "ANTHROPIC_API_KEY, or run `ant auth login`), then restart the app.")


class TutorError(Exception):
    """A turn that failed; `message` is safe to show the learner. `kind` is one of key,
    sdk, refusal, rate_limit, overloaded, connection, api, cancelled."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def echo_content(blocks: list[dict]) -> list[dict]:
    """The assistant content to send back next turn. Blocks are kept unchanged, except that
    after a mid-output fallback the thinking, redacted_thinking and tool_use blocks before
    the last `fallback` block are left out (the fallback block itself stays where it was)."""
    last = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    if last < 0:
        return blocks
    drop = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(blocks) if i >= last or b.get("type") not in drop]


class AnthropicBackend:
    def __init__(self):
        self._client = None

    def _sdk(self):
        try:
            import anthropic
        except ImportError:
            raise TutorError("sdk", NO_SDK)
        return anthropic

    def client(self):
        if self._client is None:
            anthropic = self._sdk()
            import os
            key = os.environ.get(KEY_VAR, "").strip()
            try:
                self._client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
            except anthropic.AnthropicError:
                raise TutorError("key", NO_KEY)
        return self._client

    def status(self) -> dict:
        try:
            c = self.client()
        except TutorError as e:
            return {"ready": False, "problem": e.kind, "message": e.message, "model": MODEL}
        has = any(getattr(c, k, None) for k in ("api_key", "auth_token", "credentials"))
        if not has:
            self._client = None                 # look again next time (after a login)
            return {"ready": False, "problem": "key", "message": NO_KEY, "model": MODEL}
        return {"ready": True, "problem": None, "message": "", "model": MODEL}

    def stream_reply(self, system: str, messages: list[dict], effort: str, on_text,
                     cancelled) -> list[dict]:
        anthropic = self._sdk()
        client = self.client()
        try:
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                output_config={"effort": effort},
            ) as stream:
                for event in stream:
                    if cancelled():
                        raise TutorError("cancelled", "The session was stopped.")
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        on_text(event.delta.text)
                final = stream.get_final_message()
        except TutorError:
            raise
        except anthropic.AuthenticationError:
            raise TutorError("key", "The API key was not accepted. " + NO_KEY)
        except anthropic.PermissionDeniedError:
            raise TutorError("key", "This API key may not use the tutor's model "
                                    f"({MODEL}). Check the key's workspace in the Console.")
        except anthropic.RateLimitError:
            raise TutorError("rate_limit", "Too many requests right now. Wait a minute and "
                                           "send your line again.")
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise TutorError("overloaded", "The tutor service is having trouble. Try again "
                                               "in a moment.")
            raise TutorError("api", f"The request was refused ({e.status_code}). Try again, or "
                                    "restart the session.")
        except anthropic.APIConnectionError:
            raise TutorError("connection", "No connection to the Anthropic API. Check the "
                                           "internet connection and try again.")
        except TypeError as e:                  # the SDK found no credentials at all
            if "authentication" in str(e).lower():
                self._client = None
                raise TutorError("key", NO_KEY)
            raise
        if final.stop_reason == "refusal":
            raise TutorError("refusal", "The tutor could not answer that line. Try saying it "
                                        "another way.")
        return echo_content([b.to_dict() for b in final.content])


def load_backend():
    """The backend the app uses: DANISH_TUTOR_BACKEND may name a .py file whose `Backend`
    class replaces the API (the tests and the screenshots use a scripted fake); otherwise
    the Anthropic API."""
    import importlib.util
    import os
    path = os.environ.get("DANISH_TUTOR_BACKEND")
    if path:
        spec = importlib.util.spec_from_file_location("dansk_tutor_backend", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Backend()
    return AnthropicBackend()
