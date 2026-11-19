# Example data

Everything in this folder is **invented example data**. No real learner, session, score or
mistake is recorded here. It exists so the dashboard can be built and `verify.py` can run on a
fresh clone.

- `spaced-repetition.json`, `session-log.json`, `progress-db.json`, `learner-profile.json`:
  the four files the dashboard reads, in the shapes it reads. Each carries a `_note` key saying
  it is invented. Only the keys the dashboard or the skill read are filled in; a real Fluent
  database holds more.
- `words/`: 13 word notes and 1 grammar note, in the format the skill writes.
- `sessions/`: 2 session records, one full (15 minutes) and one short (5 minutes).

The Danish words, forms and example sentences are ordinary Danish. The dates, mastery levels,
easiness factors, accuracies and minutes are made up to show the format.
