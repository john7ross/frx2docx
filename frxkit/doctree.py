# -*- coding: utf-8 -*-
"""Промежуточная модель документа для обратного пути.

Читатели (docxread, textread, pdfread) собирают эту модель, писатель
frxwrite превращает её в шаблон FastReport. Все размеры — в units
FastReport (1/96 дюйма), кегли — в пунктах, цвета — 'RRGGBB'.

    Document
      sections: [Section]
    Section
      width, height        размер листа в units
      margins              {left, right, top, bottom} в units
      landscape            bool
      body, header, footer списки блоков
    Блоки
      {"type": "p",     runs, align, indent, space_before, space_after,
                        line_height, keep_height}
      {"type": "table", cols, rows}
      {"type": "image", data, width, height, align}
      {"type": "abs",   x, y, w, h, runs, align, valign, borders, fill}
      {"type": "space", height}
    Ячейка таблицы
      {runs, colspan, rowspan, align, valign, borders, border_color,
       border_width, fill}
    Фрагмент
      {text, bold, italic, underline, strike, size, face, color}
"""

from __future__ import annotations

from .common import MM_TO_UNIT, PT_TO_UNIT

A4 = (210.0 * MM_TO_UNIT, 297.0 * MM_TO_UNIT)
DEFAULT_MARGINS = {"left": 20.0 * MM_TO_UNIT, "right": 15.0 * MM_TO_UNIT,
                   "top": 15.0 * MM_TO_UNIT, "bottom": 15.0 * MM_TO_UNIT}
DEFAULT_FONT = "Times New Roman"
DEFAULT_SIZE = 11.0


def run(text, **kwargs):
    frag = {"text": text, "bold": False, "italic": False, "underline": False,
            "strike": False, "size": None, "face": None, "color": None}
    frag.update(kwargs)
    return frag


def paragraph(runs, align="Left", indent=0.0, space_before=0.0,
              space_after=0.0, line_height=None):
    return {"type": "p", "runs": runs, "align": align, "indent": indent,
            "space_before": space_before, "space_after": space_after,
            "line_height": line_height}


def cell(runs, colspan=1, rowspan=1, align="Left", valign="Top",
         borders=None, fill=None, border_color="000000", border_width=1.0):
    return {"runs": runs, "colspan": colspan, "rowspan": rowspan,
            "align": align, "valign": valign,
            "borders": borders if borders is not None
            else {"t": 1, "r": 1, "b": 1, "l": 1},
            "border_color": border_color, "border_width": border_width,
            "fill": fill}


def table(cols, rows):
    return {"type": "table", "cols": cols, "rows": rows}


def image(data, width, height, align="Left"):
    return {"type": "image", "data": data, "width": width, "height": height,
            "align": align}


def space(height):
    return {"type": "space", "height": height}


def section(width=None, height=None, margins=None, landscape=False):
    return {"width": width or A4[0], "height": height or A4[1],
            "margins": dict(margins or DEFAULT_MARGINS),
            "landscape": landscape,
            "body": [], "header": [], "footer": []}


def document(sections=None):
    return {"sections": list(sections or [])}


def pt(value):
    """Пункты -> units."""
    return value * PT_TO_UNIT


def mm(value):
    """Миллиметры -> units."""
    return value * MM_TO_UNIT


def plain_text(runs):
    return "".join(r.get("text", "") for r in runs)


def uniform_font(runs, default_face=DEFAULT_FONT, default_size=DEFAULT_SIZE):
    """Общий шрифт абзаца: берём самый частый среди фрагментов."""
    if not runs:
        return {"name": default_face, "size": default_size, "bold": False,
                "italic": False, "underline": False, "strike": False}
    weights = {}
    for frag in runs:
        key = (frag.get("face") or default_face,
               frag.get("size") or default_size,
               bool(frag.get("bold")), bool(frag.get("italic")),
               bool(frag.get("underline")), bool(frag.get("strike")))
        weights[key] = weights.get(key, 0) + len(frag.get("text", "")) + 1
    face, size, bold, italic, underline, strike = max(weights,
                                                      key=weights.get)
    return {"name": face, "size": size, "bold": bold, "italic": italic,
            "underline": underline, "strike": strike}


def runs_differ(runs, base):
    """Нужна ли фрагментам HTML-разметка внутри TextObject."""
    for frag in runs:
        if (bool(frag.get("bold")) != base["bold"]
                or bool(frag.get("italic")) != base["italic"]
                or bool(frag.get("underline")) != base["underline"]
                or bool(frag.get("strike")) != base["strike"]
                or (frag.get("size") and frag["size"] != base["size"])
                or (frag.get("face") and frag["face"] != base["name"])
                or frag.get("color")):
            return True
    return False
