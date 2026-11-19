"""Text helpers shared by the database script, the importer and the dashboard.

- fold(): writes Danish letters in ASCII (æ to ae, ø to oe, å to aa) so item ids, file names
  and headwords can be matched to each other.
- split_frontmatter(), section(), read_words(): parse the markdown word notes.
- word_note(), add_example(), session_note(): write notes in the same format.

Standard library only.
"""
from __future__ import annotations

import re
from pathlib import Path

# Item ids are written without Danish letters (vocab_noegle for nøgle), so both sides are
# folded the same way before matching.
FOLD = str.maketrans({"æ": "ae", "ø": "oe", "å": "aa", "Æ": "ae", "Ø": "oe", "Å": "aa"})
ARTICLE = re.compile(r"^(at|en|et)\s+")


def fold(s: str) -> str:
    return s.translate(FOLD).lower().replace(" ", "_").replace("-", "_")


def strip_article(headword: str) -> str:
    """'at købe' -> 'købe', 'en nøgle' -> 'nøgle'."""
    return ARTICLE.sub("", headword.strip())


def item_key(headword: str) -> str:
    """The folded headword without its article, as used in item ids: 'at købe' -> 'koebe'."""
    return re.sub(r"[^a-z0-9_]", "", fold(strip_article(headword.lower())))


def note_filename(headword: str) -> str:
    """'værelse' -> 'vaerelse.md', 'i morgen' -> 'i-morgen.md', 'at købe' -> 'koebe.md'."""
    return item_key(headword).replace("_", "-") + ".md"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the leading --- block. Flat scalars and [a, b] lists only, which is all the
    word notes use. Returns ({}, text) when there is no frontmatter."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw, body = text[3:end], text[end + 4:]
    meta: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            v = val.strip("'\"")
            meta[key] = None if v in ("null", "~", "") else v
    return meta, body


def section(body: str, *headings: str) -> str:
    """Text under the first '## <heading>' found, up to the next heading."""
    for heading in headings:
        m = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.M)
        if not m:
            continue
        rest = body[m.end():]
        nxt = re.search(r"^##\s+", rest, re.M)
        return (rest[:nxt.start()] if nxt else rest).strip()
    return ""


def read_words(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("*.md")):
        if p.stem.lower() in ("index", "readme"):
            continue
        meta, body = split_frontmatter(p.read_text(encoding="utf-8"))
        kind = (meta.get("type") or "").strip()
        if kind not in ("word", "grammar"):
            continue

        h = re.search(r"^#\s+(.+)$", body, re.M)
        headword = h.group(1).strip() if h else (meta.get("title") or p.stem)

        # The bold line straight after the heading holds the inflection forms.
        forms = ""
        if h:
            b = re.match(r"\*\*(.+?)\*\*", body[h.end():].lstrip("\n"))
            if b:
                forms = b.group(1).strip()

        examples = [
            re.sub(r"\(\[\[.*?\]\]\)", "", ln).strip(" -*\t").strip()
            for ln in section(body, "Eksempler").splitlines()
            if ln.strip().startswith(("-", "*"))
        ]
        out.append({
            "kind": kind,
            "file": p.name,
            "head": headword,
            "forms": forms,
            "da": " ".join(section(body, "På dansk", "Reglen").split()),
            "gloss": " ".join(section(body, "Gloss").split()),
            "ex": [e for e in examples if e][:3],
            "pos": meta.get("pos") or "",
            "gender": meta.get("gender") or "",
            "level": meta.get("level") or "",
            "learned": meta.get("learned") or "",
            "source": meta.get("source") or "",
            "notes": " ".join(section(body, "Noter").split()),
            "example_data": str(meta.get("example_data") or "").lower() == "true",
        })
    return out


# ---------------------------------------------------------------- writing notes

def session_note_name(session_id: str) -> str:
    """'session-2026-11-02' -> 'dansk-session-2026-11-02' (the note's file stem and link)."""
    return session_id if session_id.startswith("dansk-") else "dansk-" + session_id


def word_note(w: dict, learned: str, note_name: str) -> str:
    kind = w.get("kind") or "word"
    head = w["headword"]
    lines = [
        "---",
        f"type: {kind}",
        f'title: "{head}"',
        "lang: da",
        f"pos: {w.get('pos') or ('grammar' if kind == 'grammar' else '')}",
        f"gender: {w.get('gender') or 'n/a'}",
        f"level: {w.get('level') or ''}",
        f"learned: {learned}",
        f'source: "{note_name}"',
        f"tags: [danish, {kind}]",
        "---",
        "",
        f"# {head}",
        "",
    ]
    if w.get("forms"):
        lines += [f"**{w['forms']}**", ""]
    lines += ["## Reglen" if kind == "grammar" else "## På dansk", w.get("definition") or "", ""]
    lines += ["## Eksempler"]
    if w.get("example"):
        lines.append(f"- {w['example']} ([[{note_name}]])")
    lines += ["", "## Gloss", w.get("gloss") or "", ""]
    if w.get("notes"):
        lines += ["## Noter", w["notes"], ""]
    return "\n".join(lines)


def add_example(text: str, sentence: str, note_name: str) -> str:
    """Append one example line to the note's ## Eksempler section (created if missing)."""
    line = f"- {sentence} ([[{note_name}]])"
    m = re.search(r"^##\s+Eksempler\s*$", text, re.M)
    if not m:
        return text.rstrip("\n") + f"\n\n## Eksempler\n{line}\n"
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    end = m.end() + (nxt.start() if nxt else len(rest))
    block = text[m.end():end].rstrip("\n")
    tail = text[end:]
    return text[:m.end()] + block + "\n" + line + ("\n\n" + tail if tail else "\n")


def session_note(s: dict, note_name: str) -> str:
    """Session record in the format the skill used to write by hand."""
    lines = [
        "---",
        "type: session",
        f'title: "Danish session {s["date"]}"',
        f"description: {s.get('summary') or s.get('topic') or ''}".rstrip(),
        f"size: {s['size']}",
        f"input_mode: {s['input_mode']}",
        "tags: [danish, session]",
        "---",
        "",
        f"# Danish session {s['date']}",
        "",
        f"**Topic:** {s.get('topic') or ''}",
        "",
        f"**Summary:** {s.get('summary') or ''}",
        "",
        "## Errors",
        "",
    ]
    errors = s.get("errors") or []
    if not errors:
        lines += ["None logged.", ""]
    by_cat: dict[str, list] = {}
    for e in errors:
        by_cat.setdefault(e.get("category") or "other", []).append(e)
    for cat, group in by_cat.items():
        lines.append(f"**{cat.capitalize()}**")
        for e in group:
            ctx = f" {e['context']}." if e.get("context") else ""
            lines.append(f"- Said: \"{e['said']}\". Correct: \"{e['correct']}\".{ctx} "
                         f"Severity: {e.get('severity') or 'moderate'}.")
        lines.append("")
    lines += ["## Listening", ""]
    listening = s.get("listening") or []
    if listening:
        lines += ["| # | Sentence | Result |", "|---|---|---|"]
        for n, li in enumerate(listening, 1):
            lines.append(f"| {n} | {li['sentence']} | {li['result']} |")
    else:
        lines.append("No listening block.")
    lines += ["", "## New words", ""]
    new = s.get("new_words") or []
    links = []
    for w in new:
        stem = note_filename(w["headword"])[:-3]
        links.append(f"[[{stem}]]" if stem == w["headword"] else f"[[{stem}|{w['headword']}]]")
    lines += [", ".join(links) if links else "None.", ""]
    lines.append(f"**Time:** {s.get('duration_minutes', 0)} minutes.")
    if s.get("input_mode") == "typed":
        lines.append("The learner typed instead of speaking this time.")
    return "\n".join(lines) + "\n"
