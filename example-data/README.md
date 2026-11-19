# Example data

Everything in this folder is **invented example data**. No real learner, session, score or
mistake is recorded here. It exists so the dashboard can be built and `verify.py` can run on a
fresh clone.

- `spaced-repetition.json`, `session-log.json`, `progress-db.json`, `learner-profile.json`:
  Fluent-format files, as read by the dashboard's JSON mode and by
  `scripts/import_fluent.py`. Each carries a `_note` key saying it is invented. Only the keys
  those two read are filled in; a real Fluent folder holds more. The plugin itself does not
  need Fluent: these files exist so the import and the dashboard can be tested.
- `words/`: 13 word notes and 1 grammar note, in the format `record` writes when `notes_dir` is set.
- `sessions/`: 2 session records, one full (15 minutes) and one short (5 minutes).

The Danish words, forms and example sentences are ordinary Danish. The dates, mastery levels,
easiness factors, accuracies and minutes are made up to show the format.
