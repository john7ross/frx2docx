# -*- coding: utf-8 -*-
"""Чтение .md / .txt в модель документа.

Markdown разбирается в объёме, который реально встречается в договорах:
заголовки, абзацы, списки, таблицы в трубах, горизонтальные линейки,
цитаты и inline-оформление (**жирный**, *курсив*, ~~зачёркнутый~~, `код`).
Обычный .txt читается как последовательность абзацев, разделённых пустой
строкой.
"""

from __future__ import annotations

import os
import re

from . import doctree

HEADING_SIZES = {1: 18.0, 2: 15.0, 3: 13.0, 4: 12.0, 5: 11.0, 6: 11.0}
BODY_SIZE = 11.0
BULLET = "• "

INLINE_RE = re.compile(
    r"(\*\*\*.+?\*\*\*|\*\*.+?\*\*|__.+?__|~~.+?~~|`[^`]+`"
    r"|(?<![\w*])\*(?!\s)[^*]+?(?<!\s)\*(?![\w*])"
    r"|(?<![\w_])_(?!\s)[^_]+?(?<!\s)_(?![\w_]))", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")
RULE_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$")


def read_text(path, warnings):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = _decode(raw)
    markdown = os.path.splitext(path)[1].lower() in (".md", ".markdown")
    section = doctree.section()
    section["body"] = (parse_markdown(text, warnings) if markdown
                       else parse_plain(text))
    return doctree.document([section])


def _decode(raw):
    for codec in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
def parse_plain(text):
    blocks = []
    for chunk in re.split(r"\r?\n\s*\r?\n", text.replace("\r\n", "\n")):
        body = chunk.strip("\n")
        if not body.strip():
            continue
        blocks.append(doctree.paragraph(
            [doctree.run(body, size=BODY_SIZE)],
            align="Justify" if len(body) > 200 else "Left",
            space_after=doctree.pt(6)))
    return blocks


# --------------------------------------------------------------------------
def parse_markdown(text, warnings):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    buffer = []
    index = 0

    def flush():
        if not buffer:
            return
        body = " ".join(x.strip() for x in buffer).strip()
        buffer.clear()
        if body:
            blocks.append(doctree.paragraph(
                inline(body, BODY_SIZE), align="Justify",
                space_after=doctree.pt(6)))

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush()
            index += 1
            continue

        if RULE_RE.match(line):
            flush()
            blocks.append(doctree.space(doctree.pt(6)))
            blocks.append(_rule())
            blocks.append(doctree.space(doctree.pt(6)))
            index += 1
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            size = HEADING_SIZES.get(level, BODY_SIZE)
            runs = inline(heading.group(2), size)
            for frag in runs:
                frag["bold"] = True
            blocks.append(doctree.paragraph(
                runs, align="Center" if level == 1 else "Left",
                space_before=doctree.pt(10), space_after=doctree.pt(6)))
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines) \
                and TABLE_SEP_RE.match(lines[index + 1]):
            flush()
            table, index = _table(lines, index)
            blocks.append(table)
            continue

        item = LIST_RE.match(line)
        if item:
            flush()
            marker = item.group(1)
            prefix = BULLET if marker in "-*+" else marker + " "
            blocks.append(doctree.paragraph(
                inline(prefix + item.group(2), BODY_SIZE),
                indent=0.0, space_after=doctree.pt(2)))
            index += 1
            continue

        if stripped.startswith(">"):
            flush()
            runs = inline(stripped.lstrip("> ").strip(), BODY_SIZE)
            for frag in runs:
                frag["italic"] = True
            blocks.append(doctree.paragraph(runs, indent=doctree.mm(10),
                                            space_after=doctree.pt(6)))
            index += 1
            continue

        buffer.append(line)
        index += 1

    flush()
    return blocks


def _rule():
    return doctree.table([doctree.mm(170)], [{
        "height": doctree.pt(10),
        "cells": [doctree.cell([doctree.run("", size=1.0)],
                               borders={"t": 1, "r": 0, "b": 0, "l": 0})]}])


def _table(lines, index):
    header = _split_row(lines[index])
    rows = []
    index += 2
    body = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        body.append(_split_row(lines[index]))
        index += 1
    width = doctree.mm(170) / max(len(header), 1)
    cols = [width] * len(header)

    rows.append({"height": 0.0, "cells": [
        doctree.cell(_bold(inline(text, BODY_SIZE)), align="Center",
                     fill="EFEFEF") for text in header]})
    for line in body:
        cells = []
        for i in range(len(header)):
            text = line[i] if i < len(line) else ""
            cells.append(doctree.cell(inline(text, BODY_SIZE)))
        rows.append({"height": 0.0, "cells": cells})
    return doctree.table(cols, rows), index


def _split_row(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _bold(runs):
    for frag in runs:
        frag["bold"] = True
    return runs


# --------------------------------------------------------------------------
def inline(text, size):
    """Markdown-разметка внутри строки -> фрагменты."""
    runs = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            runs.append(doctree.run(_unescape(text[pos:m.start()]), size=size))
        token = m.group(0)
        if token.startswith("***"):
            runs.append(doctree.run(token[3:-3], size=size, bold=True,
                                    italic=True))
        elif token.startswith("**") or token.startswith("__"):
            runs.append(doctree.run(token[2:-2], size=size, bold=True))
        elif token.startswith("~~"):
            runs.append(doctree.run(token[2:-2], size=size, strike=True))
        elif token.startswith("`"):
            runs.append(doctree.run(token[1:-1], size=size,
                                    face="Courier New"))
        else:
            runs.append(doctree.run(token[1:-1], size=size, italic=True))
        pos = m.end()
    if pos < len(text):
        runs.append(doctree.run(_unescape(text[pos:]), size=size))
    return runs or [doctree.run("", size=size)]


def _unescape(text):
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)
