# Details

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Plugin and single-plugin marketplace manifests |
| `skills/dansk/SKILL.md` | The `/dansk` launcher: starts the app and gives the address |
| `skills/dansk/session-rules.md` | The tutor's rules for every mode; the system prompt is built from it |
| `skills/dansk/config.example.json` | Every setting with its default |
| `scripts/dansk_db.py` | SQLite store, SM-2 scheduler, command line |
| `scripts/dansk_text.py` | ASCII folding, word note parsing and writing (shared) |
| `scripts/import_fluent.py` | One-way import from Fluent-format JSON |
| `scripts/speak.py` | Speaks Danish: a local text-to-speech daemon, else the system voice |
| `scripts/dansk_app.py` | Local web app server: serves `app/dist` and a JSON API over the database |
| `scripts/dansk_practice.py` | Practice sessions: prompt, stream filter, events, saving |
| `scripts/dansk_tutor.py` | The tutor backend: the Anthropic API through the official Python SDK |
| `app/` | The app's source (Vite, React, TypeScript, Astryx); `app/dist` is the committed build |
| `dashboard/` | Static export: dashboard builder and its HTML template |
| `tests/` | Unit tests (temp folders only); `tests/fake_tutor.py` is a scripted tutor with no network |
| `verify.py` | End-to-end check, prints `verify: PASS` or `verify: FAIL at <step>` |

## Settings

The scripts read `config.json` in the data folder, or the file named in `DANISH_TUTOR_CONFIG`. The data folder is `DANISH_TUTOR_HOME` if set, else `~/.claude/danish-tutor` when it exists (the plugin's older folder), else `~/.danish-tutor`. Every key is optional; `skills/dansk/config.example.json` lists them all. The scripts use:

- `db_path`: the database file. Default `dansk.db` in the data folder. `DANISH_TUTOR_DB` overrides it, and `--db` overrides both.
- `notes_dir`: empty by default (off). When set, `record` also writes markdown word notes to `<notes_dir>/words/` and a session record to `<notes_dir>/sessions/` after the database commit, in the format below.
- `level`, `target_level`, `support_language`: copied to the learner row when a session is recorded; also given to the tutor.
- `learner_name`, `goal`: given to the tutor. `goal` also picks the three topic suggestions for "Learn 10 new words".
- `voice`: `auto` (default: the local daemon if it answers, else the system voice), `local-daemon` or `system`.
- `listen_rate`, `replay_rate`: words per minute for the system voice (default 150, and 130 for "Replay slower").

Environment variables: `DANISH_TUTOR_ANTHROPIC_KEY` (see "Practice"), `CLV_PORT`, `CLV_SOCKET`, `CLV_HOME` (see `speak.py`), `DANISH_TUTOR_BACKEND` (a Python file with a `Backend` class that replaces the API; the tests use it).

## The database

One SQLite file, created on first use (the app creates an empty one on its first start). All SQL is in `scripts/dansk_db.py`, behind small functions (`insert_word`, `update_schedule`, `due_items` and so on). Column types are plain (TEXT, INTEGER, REAL) and dates are ISO `YYYY-MM-DD` strings, so a PostgreSQL backend means reimplementing those functions. The SQLite-specific parts are `INTEGER PRIMARY KEY` row ids (`SERIAL` or identity columns in PostgreSQL) and `lastrowid`.

| Table | Columns |
|---|---|
| `meta` | `key`, `value`. Holds `schema_version` (now `2`), `example_data` when the example files were imported, and `app_review_seconds:<session id>` for time spent reviewing in the app |
| `learner` | one row: `level`, `target_level`, `support_language` |
| `words` | `headword` (unique), `kind` (`word` or `grammar`), `pos`, `gender`, `level`, `forms`, `definition`, `gloss`, `notes`, `learned`, `source` |
| `examples` | `word_id`, `sentence`, `session_id` |
| `items` | `id` (`vocab_noegle`, `grammar_...`, `error_...`), `kind` (`vocabulary`, `grammar`, `error_pattern`), `content`, `answer`, `category`, `difficulty`, `word_id`, `easiness_factor`, `interval_days`, `repetitions`, `due_date`, `last_reviewed`, `total_reviews`, `mastery_level`, and for error cards `description` (what the mistake is about), `context` (where it came up), `noted` (date last seen) |
| `reviews` | `item_id`, `session_id`, `date`, `quality`, `ef_after`, `interval_after` |
| `sessions` | `id` (`session-YYYY-MM-DD`, then `-2`, `-3` the same day), `date`, `duration_minutes`, `size`, `input_mode`, `topic`, `skills` (JSON list as text), `accuracy`, `summary` |
| `errors` | `session_id`, `pattern_id`, `category`, `said`, `correct`, `context`, `severity` |
| `listening` | `session_id`, `sentence`, `result` (`understood_fully`, `gist_only`, `missed`) |

`mastery_level` is our own rule, not part of SM-2: `min(5, repetitions)`.

Migration: opening a version 1 database adds the three `items` columns with `ALTER TABLE` (existing rows keep NULL) and sets `schema_version` to `2`. Error cards without a `context` fall back to the latest logged error for that pattern.

## Command line

```
python scripts/dansk_db.py init
python scripts/dansk_db.py due [--limit N] [--json]
python scripts/dansk_db.py words [--json]
python scripts/dansk_db.py record [--file PAYLOAD.json]
python scripts/dansk_db.py stats [--json]
```

Every command takes `--db PATH` and `--today YYYY-MM-DD`. `due`, `words` and `stats` never create a database; with none present they report a first session.

- `due --json`: `due_count`, `due_items` (due on or before today, oldest first), `error_patterns` (most frequent first, with the latest wording), `learner`, `first_session`.
- `record`: one JSON payload on standard input or from `--file`. Its shape is in `skills/dansk/session-rules.md` (the same payload the app saves). Unknown keys are refused, so a typo cannot drop data. The whole payload is checked first: on any problem it prints every problem and exits 1 having written nothing. Then everything is written in one transaction; a database or disk error rolls it back and exits 2. On success it prints `saved <session id>, N reviews, N new words, N errors; X items due tomorrow` (X counts every item due on or before the day after the session).
  - A review runs SM-2 on the item and is logged in `reviews`.
  - A new word inserts the word, its example and an item (`vocab_` or, for `kind: grammar`, `grammar_`, then the headword folded to ASCII without `at`, `en` or `et`), due the next day with EF 2.5. A headword already present only gets the new example; its schedule is not reset.
  - An error is logged. Item `error_<pattern_id>` is created (content = what was said, answer = the correct form, context and date noted, due the next day) or, if it exists, set back to repetitions 0 and interval 1, due the next day, EF unchanged, with the new date noted.

## Spaced repetition: SM-2

Source: P. Wozniak (1990), "SuperMemo 2: Algorithm", <https://super-memory.com/english/ol/sm2.htm>. Rules from that page:

- Quality of a response is 0 to 5.
- A new item starts with easiness factor (EF) 2.5.
- I(1) = 1 day, I(2) = 6 days, I(n) = I(n-1) * EF for n > 2; fractions are rounded up.
- EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), never below 1.3.
- If q < 3, repetitions start again from I(1) without changing the EF.

Where the page leaves room: for q >= 3 the EF is updated first and the new interval uses it (I(n) = ceil(I(n-1) * EF')). For q < 3 the EF is kept, repetitions become 0 and the interval 1 day. The EF is rounded to 6 decimals so float noise cannot add a day. The due date is the review date plus the interval.

The page also says (step 7) to repeat, the same day, every item that scored below 4, until all score at least 4. The scheduler does not do it; the app's review does, in part: Again (1) and Hard (3) put the card at the end of the queue once more. Our reading: only the first grade of the day is stored and sets the schedule, and the repeat is practice that changes nothing, because the page describes the repeat as a drill after the graded review, not as a new review.

Worked example (also in `tests/test_sm2.py` and `verify.py`): a new item answered 5, 5, 5 gets EF 2.6, 2.7, 2.8 and intervals 1, 6, ceil(6 * 2.8) = 17. A 2 after that resets the interval to 1 with EF 2.8 kept. Repeated 3s lower the EF by 0.14 each time until it stops at 1.3.

## Importing from Fluent

```
python scripts/import_fluent.py --data DIR [--words DIR] [--db PATH]
```

One way; it never writes to the source. It reads `spaced-repetition.json` (items as an object keyed by id or as a list; keys `id`/`type` or `item_id`/`item_type`; types `vocabulary`, `grammar`, `grammar_rule` (stored as `grammar`), `error_pattern`), `session-log.json` and `learner-profile.json`. Schedule fields are copied when present: `easiness_factor`, `interval_days`, `repetitions`, `due_date`, `last_reviewed`, `total_reviews`, `mastery_level`. Missing ones start at EF 2.5, interval 0 and repetitions 0. If `mistakes-db.json` is there, it adds to error cards: the pattern's `description`, the `context` of its latest example and the date it was last seen (the latest example's `date`, else `last_occurred`, else `last_seen`), and fills an empty content or answer from that example. It reads `error_patterns` as an object keyed by id or a list with `id` or `pattern_id`, matches the item `<id>` or `error_<id>`, fills only empty fields and never creates items. Word notes come from `--words` (default `DIR/words` if it exists), parsed as the dashboard parses them. Anything already in the database (same headword, item id or session id) is skipped, so you can rerun it. It prints what it added.

## speak.py

```
python scripts/speak.py [--rate WPM] [--voice auto|local-daemon|system] "sentence"
python scripts/speak.py --stop
```

Backends in order (setting `voice`, or `--voice`):

1. A local text-to-speech daemon that speaks this small JSON protocol, for example claude-local-voice. Windows: TCP `127.0.0.1:<CLV_PORT>` (default 47821). macOS and Linux: the Unix socket `CLV_SOCKET`, default `<CLV_HOME>/voice.sock` with `CLV_HOME` default `~/.claude-local-voice`. One JSON object per connection, `{"runs": [{"lang": "da", "text": "..."}]}` or `{"stop": true}`: connect (1.5 second timeout), send, shut down the write side, close. No rate is sent. If nothing answers, the next backend is used.
2. The system voice:

- macOS: `say` with "Sara (Enhanced)", else the first voice that `say -v '?'` lists as `da_DK`.
- Windows: PowerShell with `System.Speech`, using the first enabled voice whose culture starts with `da`. SAPI takes a rate from -10 to 10, not words per minute; the script uses its own approximation, not a measured one: `round((wpm - 150) / 15)`, clamped. `System.Speech` may not list every installed voice. Not tested with a Danish voice.
- Linux: `espeak-ng -v da`, if installed.

The sentence is never printed or logged, and never passes through a shell: it reaches `say` and `espeak-ng` on standard input and PowerShell in an environment variable, with argument lists only. Exit codes: 0 spoken (or stopped), 1 bad arguments, 3 no Danish voice (with a one-line hint on how to add one), 4 the speech program failed.

## The app

```
python scripts/dansk_app.py [--db PATH] [--port N] [--no-browser] [--demo] [--today YYYY-MM-DD]
```

Standard library only, plus the `anthropic` package for Practice; Windows and macOS. The database is found as in `dansk_db.py` (`--db`, `DANISH_TUTOR_DB`, `db_path`, then the default). With none it creates an empty one and says so. `--demo` imports `example-data` into a temporary database, serves it with "today" fixed to 2026-11-06 (unless `--today` is given) and deletes it on exit. It listens on 127.0.0.1, port 8765 or the next free one, prints the URL and opens the browser unless `--no-browser`. Ctrl+C, SIGTERM or Ctrl+Break (Windows) stops it.

Pages: overview (practice buttons, due today, words known, streak, minutes this week, a 14-day chart, error patterns due, recent sessions); practice (below); review (due items, oldest first; Space reveals the answer); word bank (search, filters, sortable columns, review history, edit and delete); sessions (errors and listening results). A banner shows when the database holds the example data. Overview, word bank and sessions load again when the window gets focus or a practice session is saved.

An error card shows "A mistake from <date>", the description and context, then "You said" and "Correct" after the reveal. Two mistakes joined by " / " are shown as pairs only when both sides split into the same number of parts. "Fix this card" edits what a card shows (content, answer, description, context; a word card edits the word) or deletes it with its review history; the schedule is not changed. Again and Hard bring the card back at the end of the queue (see the SM-2 section). A card at its first review notes that every grade schedules 1 day.

Grades map to SM-2 quality: Again 1 (incorrect response; the correct one remembered), Hard 3 (correct with serious difficulty), Good 4 (correct after a hesitation), Easy 5 (perfect response). The interval on each button comes from the server's preview, which calls the same `sm2()` as the review itself; the browser computes no schedule. "Streak" here is the number of consecutive days with a session ending today or yesterday (0 otherwise). The static export counts back from the latest session instead.

Voice: "Hear it", replies and listening sentences go to `POST /api/speak`, which uses the local daemon or the system voice (as in `speak.py`, the text is never logged). When the server has neither, the browser's `speechSynthesis` with a `da` voice is used. The page shows which: "Local voice", "System voice", "Browser voice" or none.

### Reviews done in the app

The app uses one session row per day: id `app-review-YYYY-MM-DD`, `input_mode` typed, `size` small, `skills` `["vocabulary"]`, topic "Review in the app". `duration_minutes` is the time on the cards that day (at most 600 seconds per card), rounded to whole minutes; the seconds are kept in `meta`. These rows count towards streak and minutes like any session and cannot clash with `session-YYYY-MM-DD` ids from `record`.

### API

JSON under `/api/`.

- Reads: `GET summary`, `due`, `patterns`, `words?q=&kind=&level=&due=` (`kind` word or grammar, `due` due or not_due), `words/<id>` (with examples, items and review history), `sessions`, `sessions/<id>` (errors, listening, reviews), `review/preview?item_id=` (next interval, EF and due date for qualities 1, 3, 4, 5).
- Writes: `POST review` `{item_id, quality 0..5, elapsed_seconds}` runs `dansk_db.apply_review` and logs a review row. `PUT words/<id>` changes `headword`, `forms`, `definition`, `gloss`, `pos`, `gender`, `level`, `notes` (a linked item's content and answer follow the headword and gloss). `DELETE words/<id>` removes the word, its examples, its items and their reviews. `GET`, `PUT`, `DELETE items/<id>`: one card; `PUT` changes `content`, `answer`, `description`, `context`, `category`; `DELETE` removes the card and its reviews.
- Voice: `GET voice`, `POST speak` `{text, slow}`, `POST speak/stop`.
- Practice: `GET practice` (available, the problem if not, model, modes, topic ideas, the running session), `POST practice/start` `{mode, topic}`, `GET practice/<id>/events?after=N` (long poll, up to 20 seconds), `POST practice/<id>/message` `{text, via: typed|voice}`, `POST practice/<id>/end` (wrap-up and save), `retry` (save again), `stop` (no save).

Each write is one transaction. Bad input gets 400 with a message and changes nothing; unknown ids give 404; the client never sees a traceback.

### Security

- Bound to 127.0.0.1 only.
- A random token per run is written into the served `index.html` (a meta tag). Every `/api/` request must send it in the `X-Dansk-Token` header, or gets 403.
- A request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` gets 403, which stops DNS rebinding.
- No CORS headers, so other sites cannot read responses. A Content-Security-Policy allows only the app's own scripts and connections; the page makes no network calls of its own (the theme's web font is left out for that reason). The server calls the Anthropic API during practice; the browser's speech recognition may send audio to the browser maker.
- Static files are served only from inside `app/dist`; `..`, encoded slashes and absolute paths give 404.

### Building the app

`app/dist` is committed, so plugin users need no Node. To rebuild after changing `app/src`: `cd app && npm ci && npm run build` (Node 24 was used). The build escapes non-ASCII characters, drops licence comments and writes `app/dist/THIRD_PARTY_NOTICES.txt` with each bundled package, version and licence text. The UI uses Astryx (`@astryxdesign/core`, MIT); `app/AGENTS.md` holds its notes for coding agents.

## Practice

The tutor runs in the app server, not in the browser. `scripts/dansk_tutor.py` calls the Anthropic API with the official Python SDK (`pip install anthropic`, the only package outside the standard library):

- Model `claude-sonnet-5-5`, streamed with `client.beta.messages.stream`, `max_tokens` 16000. Effort `low` for conversation turns and `medium` for the closing turn that writes the payload.
- Server-side refusal fallback: beta `server-side-fallback-2026-07-01` with `fallbacks="default"`. A `refusal` stop reason ends the turn with a message.
- The system prompt (`skills/dansk/session-rules.md`, the app's own rules, the learner's settings, due cards and known words) is sent with prompt caching.
- Credentials: `DANISH_TUTOR_ANTHROPIC_KEY` if set, passed to the client explicitly; otherwise the SDK finds `ANTHROPIC_API_KEY` or an `ant auth login` profile itself. The key is never stored, logged or shown. No key or no SDK: Practice says what to do and the rest of the app works.
- Errors (authentication, permission, rate limit, server, connection) become one readable line in the chat.

Modes: `chat` (Speaking, 15 minutes), `short` (5 minutes), `listen` (Listening drill) and `words` (Learn 10 new words on a topic). One session runs at a time.

The reply stream is filtered on the server, safe when a marker is split across chunks:

- `<listen>sentence</listen>`: a hidden listening sentence, sent as its own event, spoken, and shown only after the learner answers.
- `<fix>{"said", "correct", "why", ...}</fix>`: a live correction, shown under the learner's line.
- Lines starting with a signal emoji (microphone, speaker, hourglass, check): turn state for the status chip.
- The final ```json block: the session payload, never shown.

Saving: every live correction not already in the payload's `errors` is added. The payload is checked and written in one transaction by the same code as `dansk_db.py record`. On success the chat shows the saved line; on failure it shows the problems, the payload is written to `dansk-payload-<date>-<id>.json` in the system temp folder, and "Try saving again" retries. Ending, stopping or closing the tab ends the session; a session with no poll for 90 seconds is stopped. Stopping the server stops the session.

The conversation window: a push-to-talk button (click, or hold Space) using the browser's speech recognition (`da-DK`, where the browser has it); a text box that keeps focus for dictation tools, Enter sends, optional send after a pause (off by default); replies read aloud with Replay and Stop; "Show tutor text" (on by default) and "Read replies aloud", remembered in the browser.

## The static export (dashboard)

```
python dashboard/build_dashboard.py [--db FILE | --data DIR [--words DIR]] [--out FILE] [--today YYYY-MM-DD]
```

- Default: database mode, on the configured database (same lookup as `dansk_db.py`).
- `--data` (or `DANSK_DATA_DIR`): JSON mode, reading the Fluent-format files below, with word notes from `--words` (or `DANSK_WORDS_DIR`, default `<data>/words`).
- `--out`: the HTML file. Default `dansk-dashboard.html` in the system temp folder.
- `--today`: a fixed "today", so due counts are reproducible.

Database mode turns rows into the shapes JSON mode reads, then uses the same code. Four numbers are computed from the sessions table, not stored: session count, accuracy (mean of the sessions that have one), streak (consecutive days ending at the latest session) and practice minutes per skill. On the imported example data these differ slightly from the hand-written example profile; word, item and due counts are identical. The page is static: data baked in at build time, nothing loaded from the network, no server.

## File formats

### Word notes and session records

Written by `record` only when `notes_dir` is set, and read by the importer and JSON mode. Word note: frontmatter `type` (`word` or `grammar`), `title`, `lang: da`, `pos`, `gender`, `level`, `learned`, `source`, `tags`; body `# headword`, a bold forms line, `## På dansk` (or `## Reglen`), `## Eksempler` (each line ends with a `[[dansk-session-...]]` link), `## Gloss`, optional `## Noter`. File name: the headword without `at`/`en`/`et`, with `æ`, `ø`, `å` written `ae`, `oe`, `aa` and spaces as hyphens (`værelse` is `vaerelse.md`, `at købe` is `koebe.md`). Session record: `<notes_dir>/sessions/dansk-session-YYYY-MM-DD.md` with topic, summary, errors by category, listening table, new words as links and the time.

### Fluent-format JSON (import and JSON mode)

| File | Keys used |
|---|---|
| `spaced-repetition.json` | `items` (each: `id`, `type`, `content`, `answer`, `category`, `due_date`, `mastery_level`, `total_reviews`, `easiness_factor`, plus the schedule fields above when present) |
| `session-log.json` | `sessions` (each: `session_id`, `date`, `duration_minutes`, `size`, `skills_practiced`, `accuracy`, `notes`) |
| `progress-db.json` | `overall_stats.total_sessions`, `overall_stats.accuracy_rate` (JSON mode only) |
| `learner-profile.json` | `learner.current_level`, `learner.target_level`, `learner.native_language`, `current_streak_days`, `skills.speaking.total_practice_time`, `skills.listening.total_practice_time` |

Word notes are matched to items by folding both to ASCII and dropping `at`, `en`, `et` and the `vocab_` or `grammar_` prefix.

| `mistakes-db.json` (import only) | `error_patterns` (each: `description`, `last_occurred`, `last_seen`, `examples` with `incorrect`, `correct`, `context`, `date`) |

Fluent defines more fields than these; the others are ignored.

## What was left out of the original

The tool began as one learner's private setup. Removed, not generalised: `/dansk import` for its sessions, two-machine database sync, an index note of every word, a personal text-to-speech hook (a generic daemon protocol replaces it), and the dependency on the Fluent plugin (version 0.2.0). Version 0.3.0 moved the conversation from the terminal into the app, on the Anthropic API. Its `update-db.py` is replaced by `dansk_db.py record`; no Fluent code was copied.

## verify.py

```
python verify.py
```

It checks, in order: every `.py` compiles; skill frontmatter; the dashboard build (JSON mode) from `example-data` with "today" fixed at 2026-11-06, checked against the summary line and three fixed strings; word note to item matching with four fixed due dates; SM-2 with hand-computed values; README length; banned strings and audio files; plugin manifests; the unit tests; import of `example-data` into a temporary database and a dashboard from it; a recorded payload read back, and a bad payload that writes nothing; the app build (every file `app/dist/index.html` references exists, the notices file is there, and the server serves the page with its token, refuses `/api/summary` without it and returns the example counts with it); a short practice session against the fake tutor (the correction and the hidden sentence arrive as their own events, the payload is saved with the correction as an error); repository unchanged.

Child processes and the tests run without API credentials and with the voice daemon pointed at a closed port, so verify never calls the API or speaks.

`node_modules` folders are skipped, so verify needs no Node. The banned-string check exempts e-mail addresses in `app/dist/THIRD_PARTY_NOTICES.txt`, which quotes other authors' copyright lines. It ends with `verify: PASS` or `verify: FAIL at <step>: <reason>`, exit code 0 or 1.

## Licence

PolyForm Strict 1.0.0 (`LICENSE`, with the Required Notice line at the top): free for noncommercial use; no distributing it, and no changes or new works based on it; commercial use needs permission. Versions up to commit 9ba8b3f were released under MIT. Third-party code in `app/dist` keeps its own licences, in `app/dist/THIRD_PARTY_NOTICES.txt`.

### Starting the voice daemon automatically

Many local voice daemons exit after a while idle. Set `voice_daemon_start` in the settings file
to the command that starts yours (a list of arguments, `~` allowed), for example
`["python", "~/path/to/start-server.py"]`. The app then starts it when it opens, and `speak.py`
starts it before speaking if it is not running, waiting up to 20 seconds for it to listen. A
Danish model can need more time on its first sentence after a start.

## The installable package

`pyproject.toml` builds one package, `danish_tutor`, from `scripts/`, with the built app (`app/dist`), the session rules (`skills/dansk`) and the example data inside it, and a `dansk` command that runs `dansk_app.main`. The Claude Code plugin is a thin launcher for the same app. The scripts find their files in the repository layout first and in the package layout otherwise.

The key: `DANISH_TUTOR_ANTHROPIC_KEY` if set, else whatever the Anthropic SDK finds (`ANTHROPIC_API_KEY`, or a login).

### Voice order

1. A local text-to-speech daemon, when one answers or `voice_daemon_start` is set.
2. piper with the open voice `da_DK-talesyntese-medium`, only when the optional extra is installed (`danish-tutor[voice]`, piper-tts 1.8 or newer). The voice is downloaded once into `<data folder>/voices` on the first start; until it is there the next voice speaks. Its model card gives the dataset licence as CC0 and the dataset as Språkbanken (nb.no, oai-nb-no-sbr-21).
3. The system voice (`say`, Windows speech, espeak-ng).
4. In the app, the browser's Danish voice.

Measured on one Windows desktop CPU with Python 3.13:

- Install size in a fresh venv: 64 MB without the extra, 221 MB with it (so piper and its libraries add about 157 MB), plus the voice file, 63,201,294 bytes, fetched in 7 s on this connection.
- Speed: one 115-character sentence, 3 runs through the piper command: about 7.1 s of speech in 1.31 to 1.40 s each, voice loading included. Inside the app the voice stays loaded: 1.85 s of speech took 0.68 s on the first call and 0.06 s for the next sentence.

### Cost

Prices from the Claude pricing page (2026-11-19), Sonnet 5.5 per million tokens: input $2, output $10, 5-minute cache write $2.50, cache read $0.10.

One scripted chat (start, 8 learner lines, end and save) on invented data, measured with the API's own usage counts:

| | input | cache write | cache read | output | cost |
|---|---|---|---|---|---|
| system prompt cached only | 13,416 | 6,008 | 60,080 | 2,686 | $0.075 |
| conversation cached too (now) | 44 | 11,435 | 69,641 | 2,828 | $0.064 |

The 15-minute figure in the README is an estimate, not a measurement: 15 to 30 learner lines, about 250 new tokens of conversation and 200 output tokens per line (rounded averages of the two runs above), plus the same start and save, gives about $0.09 to $0.14 with the conversation cached, and about $0.13 to $0.33 without.

