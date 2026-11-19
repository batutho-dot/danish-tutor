# Details

## Settings

The skill reads `~/.claude/dansk-tutor/config.json`, or the file named in `DANSK_TUTOR_CONFIG`.
Every key is optional. `skill/dansk/config.example.json` lists them all with their defaults,
and the table in `skill/dansk/SKILL.md` says what each one does. The most important:

- `level`, `target_level`, `goal`: what the conversation is pitched at and what topics are
  suggested.
- `support_language`: the language of the debrief and of one word hints.
- `records_dir`: where word notes (`words/`) and session records (`sessions/`) are written.
- `fluent_data_dir`, `fluent_hooks`: where the Fluent engine keeps its databases and scripts.
- `speak_replies`, `listen_command`, `listen_rate`, `replay_rate`: speech output.

## The dashboard

```
python dashboard/build_dashboard.py [--data DIR] [--words DIR] [--out FILE] [--today YYYY-MM-DD]
```

- `--data` (or `DANSK_DATA_DIR`): folder with the JSON files. Default `~/.claude/fluent-data`.
- `--words` (or `DANSK_WORDS_DIR`): folder with the word notes. Default `<data>/words`.
- `--out`: the HTML file. Default `dansk-dashboard.html` in the system temp folder.
- `--today`: treat a fixed date as today, so due counts are reproducible (used by `verify.py`).

The page is static: the data is baked into it at build time, it loads nothing from the network
and it has no server. Rebuild it after each session.

## File formats

Worked out from what the skill and the dashboard read and write. Where a format could not be
worked out from those two, it says so.

### Read by the dashboard

| File | Keys used |
|---|---|
| `spaced-repetition.json` | `items` (object keyed by item id; each item: `id`, `type` (`vocabulary`, `grammar` or `error_pattern`), `content`, `answer`, `category`, `due_date`, `mastery_level`, `total_reviews`, `easiness_factor`), `review_queue.today`, `review_queue.tomorrow` |
| `session-log.json` | `sessions` (list; each: `session_id`, `date`, `duration_minutes`, `size`, `skills_practiced`, `accuracy`, `notes`) |
| `progress-db.json` | `overall_stats.total_sessions`, `overall_stats.accuracy_rate` |
| `learner-profile.json` | `learner.current_level`, `learner.target_level`, `learner.native_language`, `current_streak_days`, `skills.speaking.total_practice_time`, `skills.listening.total_practice_time`, `last_updated` |
| `words/*.md` | frontmatter `type` (`word` or `grammar`), `pos`, `gender`, `level`, `learned`; body `# headword`, a bold forms line, `## På dansk` (or `## Reglen`), `## Eksempler`, `## Gloss` |

Word notes are matched to spaced-repetition items by folding both to ASCII (`æ` to `ae`, `ø`
to `oe`, `å` to `aa`), dropping `at`, `en`, `et` and the `vocab_` or `grammar_` prefix.

### Not fully known

- **The rest of the Fluent databases.** The Fluent engine keeps more files and more keys than
  the dashboard reads (for example the SM-2 interval and repetition count per item). Their
  exact shape is defined by the Fluent plugin, not by this repository, so the example data
  holds only the keys above.
- **`mistakes-db.json`.** The skill reads `error_patterns` and their `frequency` and
  `last_occurred`, but whether `error_patterns` is a list or an object, and what else each
  entry holds, could not be worked out. No example file is included.
- **`size` in the session log.** The dashboard shows a `size` per session, but the documented
  `update-db.py` payload has no `size` field, so it is not known whether Fluent stores it. The
  skill records size in the session record's frontmatter.

## What was left out of the original

The tool started as one learner's private setup. These parts were removed rather than
generalised:

- **An in-page chat tutor.** The original dashboard could also run a Danish conversation in
  the browser through a local server that held an Anthropic API key, proxied a local voice
  daemon over a Unix socket, and launched headless Claude Code to import the result. It was
  tied to one machine and has a larger security surface than a static page.
- **`/dansk import`**, which imported sessions saved by that chat.
- **Two-machine sync** of the databases through a personal notes folder.
- **An index note** listing every word in two tables: its column layout was not in the
  sources. The dashboard serves as the index.
- **A personal text-to-speech hook** that read every reply aloud. `speak_replies` covers the
  case where you have one of your own.

## Spaced repetition

The scheduling (SM-2 intervals and easiness factors) is done by the Fluent plugin's
`update-db.py`. This repository has no scheduling function, so `verify.py` skips that check
and says why. The skill never computes intervals itself.

## verify.py

Steps, in order: compile every `.py`; skill frontmatter; dashboard build from `example-data`
into a temporary folder with a fixed "today" of 2026-11-06, checking the summary line and three
fixed strings; word note to item matching with four fixed due dates; README length; banned
strings and audio files; repository unchanged. It ends with `verify: PASS` or
`verify: FAIL at <step>: <reason>`, exit code 0 or 1.
