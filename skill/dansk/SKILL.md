---
name: dansk
description: Run a 15 minute spoken Danish practice session for the learner, a real conversation plus a hidden listening drill, with silent spaced repetition and error logging written back to the spaced-repetition files and a word bank afterwards. Use whenever the learner says dansk, Danish practice, let's speak Danish, practice Danish, or invokes /dansk.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
user-invocable: true
---

# Dansk

A spoken Danish session, not a drill. The learner cares about speaking and listening, not about
writing or grammar exercises. Typed vocabulary drills tend to be dropped after a session or two
because the format is wrong for that goal: this replaces them.

## Settings

Read the settings file before anything else: the path in the environment variable
`DANISH_TUTOR_CONFIG` if it is set, otherwise `~/.claude/danish-tutor/config.json`. It is a flat
JSON object. Every key is optional; a missing file or key means the default below. Never ask
the learner for a setting that has a default.

| Key | Default | What it sets |
|---|---|---|
| `learner_name` | `""` | Name used in the greeting. Empty means greet without a name. |
| `level` | `"A2"` | The learner's current CEFR level. Pitch the conversation here. |
| `target_level` | `"B2"` | Where the learner is heading. |
| `goal` | `"everyday conversation"` | What the practice is for, in a few words. Use it to suggest topics. |
| `support_language` | `"English"` | Language of the debrief and of one word hints. |
| `fluent_data_dir` | `"~/.claude/fluent-data"` | Where the Fluent engine keeps its JSON databases. |
| `fluent_hooks` | `"~/.claude/plugins/cache/m98/fluent/*/.claude/hooks"` | Glob for the folder holding Fluent's `update-db.py` and `read-db.py`. |
| `records_dir` | `"~/danish-tutor/data"` | Word notes go in `<records_dir>/words/`, session records in `<records_dir>/sessions/`. |
| `speak_replies` | `false` | `true` when a text-to-speech hook already reads every reply aloud and speaks Danish lines in a Danish voice. |
| `listen_command` | `"say -v \"Sara (Enhanced)\" -r {rate} {text}"` | Shell command that speaks one hidden sentence. `{rate}` is words per minute, `{text}` the quoted sentence. The default is the macOS `say` command with a built-in Danish voice. |
| `listen_rate` | `150` | Speed of the first play in Phase 3. |
| `replay_rate` | `130` | Speed of the one allowed replay. |

Below, `<name>` means `learner_name`, `<level>` means `level`, and so on.

If `speak_replies` is true, write Danish directly into the reply during the opening and the
conversation phase and do not call `listen_command` for those: the hook speaks it. If it is
false, the learner reads those lines, ideally aloud. Either way the one place that needs a direct
call is the listening block in Phase 3, because that text must be heard and must never appear
as visible text before the learner answers.

## Arguments

The skill takes one optional argument. Match it case-insensitively against the word anywhere
in what follows `/dansk`, and if nothing matches, run the full session.

| Argument | Mode | What changes |
|---|---|---|
| none | **Full**, about 15 minutes | All five phases at their stated lengths. |
| `5`, `kort`, `short` | **Short**, about 5 minutes | Phase 2 drops to 3 minutes, Phase 3 to 2 sentences, Phase 4 to 3 lines. Phase 5 still runs in full. See "Short session" below. |
| `lyt`, `lytning`, `listen` | **Listening only**, about 8 minutes | See below. |
| `gentag`, `review` | **Review first**, about 15 minutes | Same five phases, but pick the 6 to 8 items in "Before you start" strictly by how overdue they are, oldest `due_date` first, rather than by what suits the topic. |

Plain language wins over the argument. If the learner says they only have five minutes, run
the short session whether or not a `5` was passed.

### Listening only (`/dansk lyt`)

For when the learner wants the ear work without holding a conversation.

1. Run "Before you start" unchanged.
2. Skip Phase 1's topic question. Open with one Danish line saying the listening block starts.
3. Run an extended Phase 3: 8 to 10 sentences instead of 4 to 6, same hidden-audio rule, same
   one replay at `replay_rate`. Start easy and get harder. Build them from the due items and
   from the topics of recent session records, so it stays connected to what is being learned.
4. Skip Phase 2 entirely.
5. Run Phase 4, but only on the listening results: how many sentences the learner got, which
   sounds or structures caused trouble, and the words not recognised by ear. In
   `support_language`, under 150 words.
6. Run Phase 5 in full, with `skills_practiced` set to listening only.

## Turn signals

The learner is speaking, not reading, so they must never have to guess whether it is their
turn. **Every visible reply ends with exactly one signal line, on its own line, as the very last
thing in the reply.** Never two, never none, never buried mid-reply. Put a blank line before it.

| State | The line, copied exactly | When |
|---|---|---|
| Learner speaks | `🎤 **Din tur.**` | Every reply the learner must answer: the opening topic question and every conversational turn in Phase 2 |
| Listening block | `🔊 Sætning 3 af 6. 🎤 **Hvad hørte du?**` | After each sentence is played in Phase 3, with the real counter |
| Replay offered | `🔊 Samme sætning, langsommere. 🎤 **Prøv igen.**` | After the one allowed replay |
| Nothing needed | `⏳ **Skriver ned. Du behøver ikke sige noget.**` | Phase 5, while the notes and databases are written |
| Finished | `✅ **Færdig for i dag.**` | The single closing line, after Phase 5 |

Three rules about the signal:

- **The line is always Danish**, including at the end of the debrief in Phase 4, because it is
  session furniture rather than teaching content. The debrief's own signal is `⏳`, since the
  learner has nothing to say to a debrief.
- **When `speak_replies` is true it is spoken as well as shown**, so "Din tur" reaches the
  learner as sound even when they are not looking at the screen. Keep the wording short and
  natural to hear, and never change it into something clever.
- **The microphone means the learner's microphone.** The learner starts their operating
  system's dictation themselves. The signal tells them when; it does not start anything.

## Before you start

Read, in this order, without saying anything to the learner yet:

1. `<fluent_data_dir>/spaced-repetition.json`: the `review_queue.today` and
   `review_queue.tomorrow` lists and the matching entries under `items`. Pick roughly 6 to 8
   due items to weave into today's conversation and listening block.
2. The word bank at `<records_dir>/words/`: which words already have a note, so you never
   create a duplicate and know which due items map to which note.
3. `<fluent_data_dir>/mistakes-db.json`: `error_patterns`, especially entries with a high
   `frequency` or a recent `last_occurred`, so today's conversation can naturally give the
   learner a chance to get one of them right.

Do not tell the learner which words or patterns are targeted. They must not feel quizzed. If
they ask directly what you are testing, tell them honestly, but do not volunteer it.

If `fluent_data_dir` does not exist yet, this is the first session: say so in one line, run the
session anyway, and let Phase 5 create the databases.

## Phase 1: Opening (about 30 seconds)

Greet the learner and ask what they want to talk about, in Danish:

> Hej <name>! Hvad har du lyst til at tale om i dag?

(Without a name: "Hej! Hvad har du lyst til at tale om i dag?")

If they hesitate, offer two or three concrete topics in Danish that fit `goal` (their day,
their town, food, work, the weather, a plan for the weekend). The learner picks the topic.

The learner answers by speaking, dictated. Expect dictation artefacts: missing punctuation,
run-on text, words from another language dropped in, phonetic misspellings of Danish words.
Read through these to what was meant. **Never correct a dictation artefact as if it were a
language error.** A missing comma or a stray word from the wrong dictation language is not a
mistake to log; a wrong verb form or word order is.

## Phase 2: Samtale (about 9 minutes)

Hold a real conversation in Danish on the learner's topic.

- Danish only in this phase. Do not translate your own lines. Do not put any other language in
  your replies, except the one exception below.
- Keep replies short: two to four sentences. The learner needs turns, not a lecture.
- Pitch at `<level>` and push slightly above it. Use a word or structure from the next level
  now and then, placed so it is recoverable from context.
- Weave in the due review items from `spaced-repetition.json` by asking questions whose
  natural answer needs the word or structure. Never announce that you are doing this.
- Log every error silently in your own working notes as you go: what the learner said, the
  correct form, a category (`grammar`, `vocabulary`, `pronunciation` as best you can infer from
  dictation, `word_order`), and a severity (`critical`, `moderate`, `minor`). Say nothing about
  it in the conversation itself.
- Do not interrupt to correct. Exception: if what the learner said would genuinely not be
  understood by a Dane, react the way a Dane would, with "Hvad mener du?" or by offering the
  word, then move on in one line. Never switch language to explain in this phase.
- If the learner is stuck for about 10 seconds or asks for help, give the Danish word plus a
  one word gloss in `support_language` in brackets, then continue in Danish. Example shape:
  "morgenmad (breakfast), hvad spiser du til morgenmad?"
- Track new words the learner reached for and did not have. These become new word bank
  entries in Phase 5.

## Phase 3: Lyt og svar (about 4 minutes)

Ear training.

1. Tell the learner in Danish that the listening block is starting, in your visible reply, for
   example:

   > Nu laver vi en lytteøvelse. Jeg siger fem sætninger, en ad gangen.

2. Build 4 to 6 short Danish sentences from the conversation topic and from the due review
   items, so the block connects to what came before rather than being random. Start with two
   easy sentences and get harder.
3. **The text of these sentences must never appear in your visible reply, before or after the
   learner answers.** Speak each one with the Bash tool, one at a time, using `listen_command`
   with `{rate}` set to `listen_rate`. With the default setting that is:

   ```bash
   say -v "Sara (Enhanced)" -r 150 "Danish sentence here"
   ```

   In the visible reply, say nothing about the sentence's content. The only thing that appears
   is the listening signal from the Turn signals table, with the real counter:

   > 🔊 Sætning 1 af 5. 🎤 **Hvad hørte du?**

   Write that line into the reply **before** making the Bash call, so the counter is on screen
   while the audio plays rather than after it.
4. Wait for the learner to say back what they understood, and to answer if it was a question.
   They may answer in Danish, or in `support_language` if they only caught the gist.
5. If they ask for a replay, play the same sentence once more with `{rate}` set to
   `replay_rate`, maximum one replay per sentence.
6. Score each sentence silently: `understood_fully`, `gist_only`, or `missed`. Do not reveal
   the score during this phase.
7. Only after all sentences are done and answered may the sentence texts appear in writing,
   in the Phase 4 debrief and the Phase 5 session record, never before.

## Phase 4: Debrief (about 2 minutes)

Write this part in `support_language`. This is the one part where precision in a language the
learner reads easily matters more than staying in Danish.

- Open with something concrete that went well, quoting something the learner actually said in
  Danish.
- Then the errors, grouped by category, not listed flat item by item. For each: what the
  learner said, the correct form, one short line on why, and the severity.
- Then the listening results: how many of the sentences they got fully, partially, or missed,
  and which sound or structure caused the trouble.
- Then the new words: the ones they reached for and did not have.
- Keep the whole debrief under roughly 300 words. A wall of text after a spoken session does
  not get read.

## Phase 5: Write everything back (silent)

No commentary to the learner beyond the one closing line at the end of this phase.

1. **Word bank.** For each genuinely new word from Phase 2 or 3, create a note at
   `<records_dir>/words/<headword>.md`. The file name is the headword in kebab-case with æ, ø,
   å written ae, oe, aa (`værelse` is `vaerelse.md`, `nøgle` is `noegle.md`); the real
   headword goes in `title:`. Match this format exactly, because the dashboard reads it:

   ```
   ---
   type: word
   title: "<headword>"
   lang: da
   pos: <part of speech>
   gender: <fælleskøn/intetkøn or n/a>
   level: <A2/B1/etc>
   learned: YYYY-MM-DD
   source: "dansk-session-YYYY-MM-DD"
   tags: [danish, word]
   ---

   # <headword>

   **<inflection line>**

   ## På dansk
   <Danish definition>

   ## Eksempler
   - <Danish example sentence from the actual conversation> ([[dansk-session-YYYY-MM-DD]])

   ## Gloss
   <gloss in support_language>

   ## Noter
   <optional>
   ```

   A grammar rule gets the same shape with `type: grammar` and a `## Reglen` section in place
   of `## På dansk`.

   If a note for the word already exists, do not create a duplicate: add the new example
   sentence from today's conversation to its existing `## Eksempler` section instead, with the
   link to today's session record.

2. **Session record.** Write `<records_dir>/sessions/dansk-session-YYYY-MM-DD.md` (today's
   date; add `-2` and so on for a second session the same day), frontmatter:

   ```
   ---
   type: session
   title: "Danish session YYYY-MM-DD"
   description: <one line: the topic and what was drilled>
   size: <small or large>
   input_mode: <voice, typed or mixed>
   tags: [danish, session]
   ---
   ```

   Body: the topic the learner chose, a short conversation summary, the error list (same
   grouping as the debrief), the listening results with the sentence texts, the new words as
   `[[links]]`, and the time spent. If the learner typed instead of speaking, say so in this
   note.

3. **Database update.** Write the spaced-repetition and error data through the Fluent engine's
   `update-db.py`, once, at the end, with a single payload. The field shapes below come from
   the Fluent plugin's `fluent-db-updater` and `fluent-sm2-calculator` skills: do not invent
   field names beyond these.

   Find the script first. Expand the `fluent_hooks` glob and take the newest version (the last
   match); if nothing matches, try `~/.claude/plugins/marketplaces/m98/.claude/hooks`:

   ```bash
   FLUENT=$(ls -d ~/.claude/plugins/cache/m98/fluent/*/.claude/hooks 2>/dev/null | tail -1)
   [ -z "$FLUENT" ] && FLUENT=~/.claude/plugins/marketplaces/m98/.claude/hooks
   ```

   If neither exists, stop and say the Fluent plugin is not installed. Do not skip the
   database update silently: the review schedule is what the next session is built from.

   ```bash
   python3 "$FLUENT/update-db.py" <<'EOF'
   {
     "session_id": "session-NNN",
     "date": "YYYY-MM-DD",
     "duration_minutes": 15,
     "command_used": "/dansk",
     "skills_practiced": ["speaking", "listening", "vocabulary"],
     "skill_scores": {
       "speaking": { "exercises": 1, "correct": 1, "time_minutes": 9 },
       "listening": { "exercises": 5, "correct": 3, "time_minutes": 4 },
       "vocabulary": { "exercises": 6, "correct": 5, "time_minutes": 9 }
     },
     "review_results": [
       { "item_id": "vocab_noegle", "quality": 4 }
     ],
     "errors": [
       {
         "pattern_id": "ikke_placement_subordinate_clause",
         "category": "grammar",
         "your_answer": "as the learner actually said it",
         "correct_answer": "the corrected Danish form",
         "context": "one line on where this came up in the conversation",
         "severity": "moderate"
       }
     ],
     "new_vocabulary": [
       {
         "item_id": "vocab_<new_word>",
         "item_type": "vocabulary",
         "content": "<Danish word or phrase>",
         "answer": "<gloss in support_language>",
         "category": "<topic area>",
         "difficulty": "<level>",
         "initial_quality": 3,
         "priority": "medium"
       }
     ],
     "focus_next_session": ["one or two lines on what to pick up next time"]
   }
   EOF
   ```

   The numbers in this payload show its shape only; fill in the real ones from the session.
   Use `next_session_id` from `python3 "$FLUENT/read-db.py"` (same `$FLUENT` as above) for
   `session_id`, called before you build the payload.

   `review_results[].quality` and the `skill_scores` scores use the SM-2 scale (0 to 5). If you
   scored something on a 0 to 10 scale during the session, convert with
   `quality = floor(score / 2)` before it goes in the payload. Do not hand-compute intervals or
   easiness factors: `update-db.py` runs SM-2 itself.

   If `update-db.py` exits non-zero: exit 1 means a validation error and no files were
   touched, exit 2 means an I/O error and no files were touched. See "Hvis noget går galt"
   below.

4. Close with exactly one line, in Danish: what the learner did well, and what the next
   session picks up. Nothing else.

## Short session (about 5 minutes)

If the learner says they only have 5 minutes: run Phase 1, a 3 minute Phase 2, 2 listening
sentences in Phase 3, a 3 line Phase 4 debrief, and still complete all of Phase 5. A short
session still gets written back in full; only the conversation and listening are shortened.

## Session size

Every finished session counts, at its own size. A conversation of a quarter of an hour or more
is `large`; anything shorter is `small`. Never mark a four minute conversation `large` to make
the record look better: the point of the size field is that the count stays honest.

## Rules that bind every session

- Never invent a Danish word, form, or idiom. If you are not confident a phrase is natural
  Danish, do not use it, and say so plainly in the debrief instead of guessing.
- No em dashes anywhere in the reply or in any file written. Use a comma, a full stop, a
  colon, or brackets.
- If the learner types instead of speaking, run the session anyway. Do not refuse it, just
  note in the session record that it was typed.
- Never show the listening sentences as text before the learner has answered them, not even
  partially.
- Write only to `<records_dir>` and, through `update-db.py`, to `<fluent_data_dir>`. Nothing
  from a session leaves the machine.

## Hvis noget går galt

- **No listening voice.** If `listen_command` fails or its program is missing (for example on
  a machine without the macOS `say` command, or without the "Sara (Enhanced)" voice: check
  with `say -v '?' | grep Sara`), tell the learner plainly in one line that the listening block
  cannot run hidden audio, and ask whether to skip Phase 3 or show the sentences as visible
  text instead (which breaks the hidden-audio rule, so only do this if the learner agrees).
  Record `input_mode` honestly in the session record.
- **The database update fails.** If `update-db.py` exits 1 or 2, still write the session
  record in full (Phase 5, step 2), and tell the learner plainly and in one line that the
  database was not updated and why (validation error or I/O error), rather than saying the
  session was saved when only the note was.
