# danish-tutor

<img src="docs/icon.png" alt="icon" width="120">

Spoken Danish practice in a local web app: a relaxed chat with small corrections as you go, a hidden listening drill, ten new words at a time, and spaced repetition. For learners around A2 to B1. One install, your own Anthropic key, and the tutor runs on the Anthropic API.

From the invented example data:

```
Tutor:   Hej! Hvad har du lyst til at snakke om i dag?
Learner: Jeg spiser ikke morgenmad, fordi jeg har ikke tid.
         Small fix: fordi jeg har ikke tid > fordi jeg ikke har tid
```

The fix becomes an error card for review.

## What you need

- **Python 3.10+** (on Windows, tick "Add python.exe to PATH") and **pipx** (`python -m pip install --user pipx`, then `python -m pipx ensurepath`) or **uv**.
- **An Anthropic API key** from console.anthropic.com. The app never asks for it, stores it or shows it.
- **Edge or Chrome** for the Talk button. Typing works too.

Claude Code and Node are not needed.

## Install and start

1. Install: `pipx install git+https://github.com/batutho-dot/danish-tutor` (or `uv tool install` with the same URL).
2. Set your key: Windows `setx ANTHROPIC_API_KEY "your-key"`, macOS `echo 'export ANTHROPIC_API_KEY="your-key"' >> ~/.zshrc`. Open a new terminal.
3. Type `dansk`. The app opens in your browser (`dansk --demo` tries it on invented data).

Voice: replies are read by your browser's Danish voice. For an offline open voice (piper, about 220 MB), install with `pipx install "danish-tutor[voice] @ git+https://github.com/batutho-dot/danish-tutor"`.

Cost: a measured 8-line chat on Sonnet 5.5 cost $0.06; a 15-minute session is estimated at $0.09 to $0.14.

Claude Code users can also add the plugin (`/plugin marketplace add batutho-dot/danish-tutor`, `/plugin install danish-tutor@danish-tutor`) and type `/dansk`. Settings: `skills/dansk/config.example.json`.

## The app

- **Practice:** Speaking (15 minutes), Short chat (5), Listening drill, Learn 10 new words. Talk or type. Replies are read aloud; switch off "Show tutor text" to practise by ear. The session is saved at the end.
- **Review:** due cards, oldest first. Error cards show the mistake, where it came up, what you said and the correct form. Again and Hard come back at the end. "Fix this card" edits or deletes a card.
- **Overview, Word bank, Sessions:** what is due, your streak, your words, past sessions.

![Review](docs/screenshots/review.png)
![Practice](docs/screenshots/practice.png)

Scheduling is SM-2 (Wozniak 1990), in `scripts/dansk_db.py`.

## Your data and privacy

Your record is one SQLite file, `~/.danish-tutor/dansk.db` (or `~/.claude/danish-tutor/` if that exists), created on first start. The conversation text goes to the Anthropic API under your key. The Talk button uses your browser's speech recognition, which may send audio to the browser maker. The app listens on 127.0.0.1 only.

Coming from the Fluent plugin? Import once:

```bash
python -m danish_tutor.import_fluent --data <your Fluent data folder> --words <your word notes folder>
```

## Limits

- The tutor's Danish is not checked against a dictionary.
- Without the piper extra, listening needs a Danish browser or system voice; not every computer has one.
- No claim about learning gains is made.

## Licence

PolyForm Strict 1.0.0 (`LICENSE`): free for noncommercial use; no distributing it, and no changes or new works based on it; commercial use needs permission. Versions up to commit 9ba8b3f were released under MIT. Bundled third-party code keeps its own licences (`app/dist/THIRD_PARTY_NOTICES.txt`). `example-data/` is invented. More: [docs/details.md](docs/details.md).
