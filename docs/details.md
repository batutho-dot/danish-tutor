# Details

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Plugin and single-plugin marketplace manifests |
| `skills/dansk/SKILL.md` | The `/dansk` session design |
| `skills/dansk/config.example.json` | Every setting with its default |
| `scripts/dansk_db.py` | SQLite store, SM-2 scheduler, command line |
| `scripts/dansk_text.py` | ASCII folding, word note parsing and writing (shared) |
| `scripts/import_fluent.py` | One-way import from Fluent-format JSON |
| `scripts/speak.py` | Speaks one hidden sentence with an installed Danish voice |
| `scripts/dansk_app.py` | Local web app server: serves `app/dist` and a JSON API over the database |
| `app/` | The app's source (Vite, React, TypeScript, Astryx); `app/dist` is the committed build |
| `dashboard/` | Static export: dashboard builder and its HTML template |
| `tests/` | Unit tests (temp folders only) |
| `verify.py` | End-to-end check, prints `verify: PASS` or `verify: FAIL at <step>` |

## Settings

The skill and the scripts read `~/.claude/danish-tutor/config.json`, or the file named in
`DANISH_TUTOR_CONFIG`. Every key is optional; `skills/dansk/config.example.json` lists them
all and the table in `skills/dansk/SKILL.md` says what each one does. The ones the scripts
use:

- `db_path`: the database file. Default `~/.claude/danish-tutor/dansk.db`. The environment
  variable `DANISH_TUTOR_DB` overrides it, and `--db` overrides both.
- `notes_dir`: empty by default (off). When set, `record` also writes markdown word notes to
  `<notes_dir>/words/` and a session record to `<notes_dir>/sessions/` after the database
  commit, in the format below.
- `level`, `target_level`, `support_language`: copied to the database's learner row when a
  session is recorded, so the dashboard shows them.

`listen_command` is empty by default, which means `scripts/speak.py`.

## The database

One SQLite file, created on first use. All SQL is in `scripts/dansk_db.py`, behind small
functions (`insert_word`, `update_schedule`, `due_items` and so on), with plain column types
(TEXT, INTEGER, REAL) and dates as ISO `YYYY-MM-DD` strings, so a PostgreSQL backend could be
added by reimplementing those functions. The SQLite-specific parts are `INTEGER PRIMARY KEY`
row ids (`SERIAL` or identity columns in PostgreSQL) and `lastrowid`.

| Table | Columns |
|---|---|
| `meta` | `key`, `value`. Holds `schema_version` (now `1`), `example_data` when the example files were imported, and `app_review_seconds:<session id>` for time spent reviewing in the app |
| `learner` | one row: `level`, `target_level`, `support_language` |
| `words` | `headword` (unique), `kind` (`word` or `grammar`), `pos`, `gender`, `level`, `forms`, `definition`, `gloss`, `notes`, `learned`, `source` |
| `examples` | `word_id`, `sentence`, `session_id` |
| `items` | `id` (`vocab_noegle`, `grammar_...`, `error_...`), `kind` (`vocabulary`, `grammar`, `error_pattern`), `content`, `answer`, `category`, `difficulty`, `word_id`, `easiness_factor`, `interval_days`, `repetitions`, `due_date`, `last_reviewed`, `total_reviews`, `mastery_level` |
| `reviews` | `item_id`, `session_id`, `date`, `quality`, `ef_after`, `interval_after` |
| `sessions` | `id` (`session-YYYY-MM-DD`, then `-2`, `-3` the same day), `date`, `duration_minutes`, `size`, `input_mode`, `topic`, `skills` (JSON list as text), `accuracy`, `summary` |
| `errors` | `session_id`, `pattern_id`, `category`, `said`, `correct`, `context`, `severity` |
| `listening` | `session_id`, `sentence`, `result` (`understood_fully`, `gist_only`, `missed`) |

`mastery_level` is our own rule, not part of SM-2: `min(5, repetitions)`.

## Command line

```
python scripts/dansk_db.py init
python scripts/dansk_db.py due [--limit N] [--json]
python scripts/dansk_db.py words [--json]
python scripts/dansk_db.py record [--file PAYLOAD.json]
python scripts/dansk_db.py stats [--json]
```

Every command takes `--db PATH` and `--today YYYY-MM-DD`. `due`, `words` and `stats` never
create a database; with none present they report a first session.

- `due --json`: `due_count`, `due_items` (due on or before today, oldest first),
  `error_patterns` (most frequent first, with the latest wording), `learner`,
  `first_session`.
- `record`: one JSON payload on standard input or from `--file`. The shape is shown in
  `skills/dansk/SKILL.md`, Phase 5. Unknown keys are refused, so a typo cannot drop data
  silently. The whole payload is checked first: on any problem it prints every problem and
  exits 1 having written nothing. Then everything is written in one transaction; a database
  or disk error rolls it back and exits 2. On success it prints
  `saved <session id>, N reviews, N new words, N errors; X items due tomorrow` (X counts
  every item due on or before the day after the session).
  - A review runs SM-2 on the item and is logged in `reviews`.
  - A new word inserts the word, its example and an item (`vocab_` or, for `kind: grammar`,
    `grammar_`, followed by the headword folded to ASCII without `at`, `en` or `et`), due the
    next day with EF 2.5. A headword already present only gets the new example; its schedule
    is not reset.
  - An error is logged; item `error_<pattern_id>` is created (content = what was said,
    answer = the correct form, due the next day) or, if it exists, set back to repetitions 0
    and interval 1, due the next day, EF unchanged.

## Spaced repetition: SM-2

Source: P. Wozniak (1990), "SuperMemo 2: Algorithm",
<https://super-memory.com/english/ol/sm2.htm>. Rules taken from that page:

- Quality of a response is 0 to 5.
- A new item starts with easiness factor (EF) 2.5.
- I(1) = 1 day, I(2) = 6 days, I(n) = I(n-1) * EF for n > 2; fractions are rounded up.
- EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), never below 1.3.
- If q < 3, repetitions start again from I(1) without changing the EF.

Our reading where the page leaves room: for q >= 3 the EF is updated first and the new
interval uses it (I(n) = ceil(I(n-1) * EF')); for q < 3 the EF is kept, repetitions become 0
and the interval 1 day. The EF is rounded to 6 decimals so float noise cannot add a day.
The due date is the review date plus the interval.

The page also says to repeat, the same day, every item that scored below 4. That is a session
practice and is not implemented by the scheduler.

Worked example (also in `tests/test_sm2.py` and `verify.py`): a new item answered 5, 5, 5 gets
EF 2.6, 2.7, 2.8 and intervals 1, 6, ceil(6 * 2.8) = 17; a 2 after that resets the interval to
1 with EF 2.8 kept. Repeated 3s lower the EF by 0.14 each time until it stops at 1.3.

## Importing from Fluent

```
python scripts/import_fluent.py --data DIR [--words DIR] [--db PATH]
```

One way, never writes to the source. Reads `spaced-repetition.json` (items as an object keyed
by id or as a list; keys `id`/`type` or `item_id`/`item_type`; types `vocabulary`, `grammar`,
`grammar_rule` (stored as `grammar`), `error_pattern`), `session-log.json` and
`learner-profile.json`. Schedule fields are copied when present: `easiness_factor`,
`interval_days`, `repetitions`, `due_date`, `last_reviewed`, `total_reviews`,
`mastery_level`. Missing ones start at EF 2.5, interval 0 and repetitions 0. Word notes come
from `--words` (default `DIR/words` if it exists), parsed exactly as the dashboard parses them.
Anything already in the database (same headword, item id or session id) is skipped, so the
import can be run again safely. It prints what it added.

## speak.py

```
python scripts/speak.py --rate WPM "sentence"
```

- macOS: `say` with "Sara (Enhanced)", else the first voice that `say -v '?'` lists as
  `da_DK`.
- Windows: PowerShell with `System.Speech`, using the first enabled voice whose culture starts
  with `da`. SAPI takes a rate from -10 to 10, not words per minute; the script uses its own
  approximation, not a measured one: `round((wpm - 150) / 15)`, clamped. `System.Speech`
  may not list every voice installed on the machine; this was not tested with a Danish
  voice.
- Linux: `espeak-ng -v da`, if installed.

The sentence never passes through a shell: it reaches `say` and `espeak-ng` on standard input
and PowerShell in an environment variable, with argument lists only. Exit codes: 0 spoken,
1 bad arguments, 3 no Danish voice (with a one-line hint on how to add one), 4 the speech
program failed.

## The app

```
python scripts/dansk_app.py [--db PATH] [--port N] [--no-browser] [--demo] [--today YYYY-MM-DD]
```

Standard library only; works on Windows and macOS. The database is found the same way as
`dansk_db.py` (`--db`, `DANISH_TUTOR_DB`, `db_path`, then the default). With no database it
says so and exits; it never creates one. `--demo` imports `example-data` into a fresh
temporary database, serves that with "today" fixed to 2026-11-06 (unless `--today` is
given) and deletes it on exit. It listens on 127.0.0.1, port 8765 or the next free one,
prints the URL and opens the browser unless `--no-browser`. Ctrl+C (or SIGTERM, or
Ctrl+Break on Windows) stops it.

The pages: an overview (due today, words known, streak, minutes this week, a 14-day chart,
error patterns due, recent sessions), review (due items oldest first; a card shows the
Danish word or the wrong sentence, and Space reveals gloss, forms, Danish definition and
examples), the word bank (search, filters, sortable columns, a detail panel with review
history, edit and delete) and sessions (errors and listening results per session). A banner
shows when the database holds the example data.

Grades map to SM-2 quality: Again 1 (incorrect response; the correct one remembered), Hard
3 (correct with serious difficulty), Good 4 (correct after a hesitation), Easy 5 (perfect
response). The interval on each button comes from the server's preview, which calls the same
`sm2()` as the review itself; the browser computes no schedule. "Streak" here is the number
of consecutive days with a session ending today or yesterday (0 otherwise), which differs
from the static export's count back from the latest session.

"Hear it" uses the browser's `speechSynthesis` with the first voice whose language starts
with `da`. With none installed the button is disabled and its tooltip says how to add one.
No audio goes through the server.

### Reviews done in the app

Each review needs a session. The app uses one session row per day, id
`app-review-YYYY-MM-DD`, `input_mode` typed, `size` small, `skills` `["vocabulary"]`, topic
"Review in the app". Its `duration_minutes` is the time spent on the cards that day (at most
600 seconds counted per card), rounded to whole minutes; the seconds are kept in `meta`.
These rows count towards the streak and the minutes like any session, and cannot clash with
`session-YYYY-MM-DD` ids from `record`.

### API

JSON under `/api/`. Reads: `GET summary`, `due`, `patterns`, `words?q=&kind=&level=&due=`
(`kind` word or grammar, `due` due or not_due), `words/<id>` (with examples, items and
review history), `sessions`, `sessions/<id>` (errors, listening, reviews),
`review/preview?item_id=` (next interval, EF and due date for qualities 1, 3, 4, 5). Writes:
`POST review` `{item_id, quality 0..5, elapsed_seconds}` runs `dansk_db.apply_review` and
logs a review row; `PUT words/<id>` changes `headword`, `forms`, `definition`, `gloss`,
`pos`, `gender`, `level`, `notes` (a linked item's content and answer follow the headword
and gloss); `DELETE words/<id>` removes the word, its examples, its items and their reviews.
Each write is one transaction. Bad input gets 400 with a message and changes nothing;
unknown ids give 404; the client never sees a traceback.

### Security

- Bound to 127.0.0.1 only.
- A random token per run is written into the served `index.html` (a meta tag). Every
  `/api/` request must send it in the `X-Dansk-Token` header, or gets 403.
- A request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` gets 403, which
  stops DNS rebinding.
- No CORS headers, so other sites cannot read responses. A Content-Security-Policy allows
  only the app's own scripts and connections; the app makes no network calls (the theme's
  web font is left out for that reason).
- Static files are served only from inside `app/dist`; `..`, encoded slashes and absolute
  paths give 404.

### Building the app

`app/dist` is committed, so plugin users need no Node. To rebuild after changing `app/src`:
`cd app && npm ci && npm run build` (Node 24 was used). The build escapes non-ASCII
characters in the emitted JavaScript and CSS, drops licence comments from the bundle and
writes `app/dist/THIRD_PARTY_NOTICES.txt` with every bundled package, its version and its
licence text. The UI is built with Astryx (`@astryxdesign/core`, MIT); `app/AGENTS.md` holds
its notes for coding agents.

## The static export (dashboard)

```
python dashboard/build_dashboard.py [--db FILE | --data DIR [--words DIR]] [--out FILE] [--today YYYY-MM-DD]
```

- Default: database mode, on the configured database (same lookup as `dansk_db.py`).
- `--data` (or `DANSK_DATA_DIR`): JSON mode, reading the Fluent-format files below, with
  word notes from `--words` (or `DANSK_WORDS_DIR`, default `<data>/words`).
- `--out`: the HTML file. Default `dansk-dashboard.html` in the system temp folder.
- `--today`: a fixed "today", so due counts are reproducible.

Database mode turns rows into the same shapes JSON mode reads and then uses the same code.
Four numbers are computed from the sessions table rather than stored: the session count,
accuracy (mean of the sessions that have one), the streak (consecutive days ending at the
latest session) and practice minutes per skill (total minutes of the sessions that practised
it). On the imported example data these differ slightly from the hand-written example
profile; the word, item and due counts are identical.

The page is static: the data is baked in at build time, it loads nothing from the network and
it has no server.

## File formats

### Word notes and session records

Written by `record` only when `notes_dir` is set, and read by the importer and JSON mode.
Word note: frontmatter `type` (`word` or `grammar`), `title`, `lang: da`, `pos`, `gender`,
`level`, `learned`, `source`, `tags`; body `# headword`, a bold forms line, `## På dansk` (or
`## Reglen`), `## Eksempler` (each line ends with a `[[dansk-session-...]]` link), `## Gloss`,
optional `## Noter`. File name: the headword without `at`/`en`/`et`, `æ`, `ø`, `å` written
`ae`, `oe`, `aa`, spaces as hyphens (`værelse` is `vaerelse.md`, `at købe` is `koebe.md`).
Session record: `<notes_dir>/sessions/dansk-session-YYYY-MM-DD.md` with topic, summary, errors
by category, listening table, new words as links and the time.

### Fluent-format JSON (import and JSON mode)

| File | Keys used |
|---|---|
| `spaced-repetition.json` | `items` (each: `id`, `type`, `content`, `answer`, `category`, `due_date`, `mastery_level`, `total_reviews`, `easiness_factor`, plus the schedule fields above when present) |
| `session-log.json` | `sessions` (each: `session_id`, `date`, `duration_minutes`, `size`, `skills_practiced`, `accuracy`, `notes`) |
| `progress-db.json` | `overall_stats.total_sessions`, `overall_stats.accuracy_rate` (JSON mode only) |
| `learner-profile.json` | `learner.current_level`, `learner.target_level`, `learner.native_language`, `current_streak_days`, `skills.speaking.total_practice_time`, `skills.listening.total_practice_time` |

Word notes are matched to items by folding both to ASCII and dropping `at`, `en`, `et` and the
`vocab_` or `grammar_` prefix.

Not known: the full shape of Fluent's other files (for example `mistakes-db.json`), which are
defined by that plugin. The importer does not read them, so past error logs are not imported;
error-pattern items in `spaced-repetition.json` are.

## What was left out of the original

The tool started as one learner's private setup. These parts were removed rather than
generalised:

- **An in-page chat tutor.** The original dashboard could also run a Danish conversation in
  the browser through a local server that held an Anthropic API key, proxied a local voice
  daemon over a Unix socket, and launched headless Claude Code to import the result. It was
  tied to one machine and has a larger security surface than a static page.
- **`/dansk import`**, which imported sessions saved by that chat.
- **Two-machine sync** of the databases through a personal notes folder.
- **An index note** listing every word in two tables. The dashboard serves as the index.
- **A personal text-to-speech hook** that read every reply aloud. `speak_replies` covers the
  case where you have one of your own.
- **The dependency on the Fluent plugin** for scheduling and saving (version 0.2.0). Its
  `update-db.py` is replaced by `dansk_db.py record`; no Fluent code was copied.

## verify.py

```
python verify.py
```

Steps, in order: compile every `.py`; skill frontmatter under `skills/`; dashboard build (JSON
mode) from `example-data` into a temporary folder with a fixed "today" of 2026-11-06, checking
the summary line and three fixed strings; word note to item matching with four fixed due
dates; SM-2 with hand-computed values; README length; banned strings and audio files; plugin
manifests; the unit tests; import of `example-data` into a temporary database and a dashboard
built from it with the same summary line and due dates; a recorded payload read back from a
temporary database, and a bad payload that writes nothing; the app build (every file
`app/dist/index.html` references exists, the notices file is there, and the server serves the
page with its token, refuses `/api/summary` without it and returns the example counts with
it); repository unchanged. `node_modules` folders are skipped, so verify does not need Node.
The banned-string check has one narrow exemption here: e-mail addresses in
`app/dist/THIRD_PARTY_NOTICES.txt`, which quotes other authors' copyright lines. It ends with
`verify: PASS` or `verify: FAIL at <step>: <reason>`, exit code 0 or 1.

## Licence

PolyForm Strict 1.0.0 (`LICENSE`, with the Required Notice line at the top): free for
noncommercial use; no distributing it, and no changes or new works based on it; commercial
use needs permission. Versions up to commit 9ba8b3f were released under MIT. Third-party code
bundled in `app/dist` keeps its own licences, listed in `app/dist/THIRD_PARTY_NOTICES.txt`.
