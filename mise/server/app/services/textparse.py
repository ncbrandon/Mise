"""Heuristic plain-text recipe parser, used when no LLM is configured
(pasted text, video captions, documents)."""
from __future__ import annotations

import re
from typing import Optional

from .ingredients import _QTY_RE, is_group_header

ING_HEAD = re.compile(r"^\W*(ingredients?|what you(?:'|’)ll need|you will need|shopping list)\b\W*$", re.I)
STEP_HEAD = re.compile(r"^\W*(instructions?|directions?|method|steps?|preparation|how to make( it)?)\b\W*$", re.I)
NOTE_HEAD = re.compile(r"^\W*(notes?|tips?)\b\W*$", re.I)
SERVES = re.compile(r"\b(?:serves|servings?|yield|makes)\b\W*(\d+)", re.I)
BULLET = re.compile(r"^\s*(?:[-*•▢□☐◦·✓✔]|\d+[.)]|step\s*\d+[:.)]?)\s*", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def _strip(line: str) -> str:
    line = EMOJI.sub("", line)
    return BULLET.sub("", line).strip()


def _looks_like_ingredient(line: str) -> bool:
    s = _strip(line)
    return bool(_QTY_RE.match(s)) and len(s) < 90


def parse_text(text: str, title: Optional[str] = None) -> dict:
    lines = [l.rstrip() for l in (text or "").splitlines()]
    # drop hashtag-only lines (social captions) but keep markdown headings like "## Ingredients"
    lines = [l for l in lines if l.strip() and not re.fullmatch(r"(\s*#\w+)+\s*", l)]
    mode = "pre"
    pre: list[str] = []
    ings: list[str] = []
    steps: list[dict] = []
    notes: list[str] = []
    section: Optional[str] = None

    for raw in lines:
        line = raw.strip().lstrip("#").strip()
        if not line:
            continue
        if ING_HEAD.match(line):
            mode = "ing"
            continue
        if STEP_HEAD.match(line):
            mode = "steps"
            section = None
            continue
        if NOTE_HEAD.match(line):
            mode = "notes"
            continue
        if mode == "ing":
            if is_group_header(line):
                ings.append(line)
            else:
                ings.append(_strip(line))
        elif mode == "steps":
            if is_group_header(line) and len(line) < 40:
                section = line.rstrip(":")
                continue
            steps.append({"text": _strip(line), "section": section})
        elif mode == "notes":
            notes.append(line)
        else:
            pre.append(line)

    # No headings found: classify line by line.
    if not ings and not steps:
        rest = []
        for line in pre:
            if _looks_like_ingredient(line):
                ings.append(_strip(line))
            else:
                rest.append(line)
        pre = []
        for line in rest:
            if len(line) > 35 and re.search(r"[a-z]", line) and ings:
                steps.append({"text": _strip(line), "section": None})
            else:
                pre.append(line)

    serv = None
    for l in pre + notes:
        m = SERVES.search(l)
        if m:
            serv = float(m.group(1))
            break
    t = title or (pre[0][:120] if pre else "Untitled recipe")
    desc_lines = pre[1:] if not title else pre
    desc = " ".join(desc_lines)[:600] or None
    return {
        "title": t,
        "description": desc,
        "servings": serv,
        "servings_text": str(int(serv)) if serv else None,
        "ingredients": [i for i in ings if i],
        "steps": [s for s in steps if s["text"]],
        "notes": "\n".join(notes) or None,
    }
