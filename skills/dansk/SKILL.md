---
name: dansk
description: Open the learner's danish-tutor app, a local web app for spoken Danish practice (casual chat with live corrections, listening drill, ten new words, flash-card review and a word bank). Use whenever the learner says dansk, Danish practice, let's speak Danish, practise Danish, or invokes /dansk.
allowed-tools: Bash
user-invocable: true
---

# Dansk

All practice happens in the danish-tutor app in the browser. This skill only starts it.

1. Start the app server in the background (it keeps running until the learner stops it):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dansk_app.py"
   ```

   On Windows `python3` may be missing or open the Microsoft Store: then run the same
   command with `python`.

2. It prints a line like `danish-tutor app: http://127.0.0.1:8765/` and opens the browser.
   Tell the learner that URL in one line, and that stopping the background task (or Ctrl+C
   in a terminal) stops the app.

3. On the very first run it prints `created a new, empty database at ...`; that is normal.
   To try the app on invented example data instead, add `--demo` to the command. Nothing
   else.

Do not run a practice session in the terminal, and do not read or change the learner's
database yourself.
