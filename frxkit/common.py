# -*- coding: utf-8 -*-
"""Единицы измерения и разбор атрибутов FastReport."""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# единицы
# --------------------------------------------------------------------------
# FastReport хранит координаты в «пикселях» 96 dpi.
# 1 unit = 1/96 дюйма = 15 twips (dxa) = 0.75 pt.
UNIT_TO_DXA = 15.0
UNIT_TO_PT = 0.75
MM_TO_DXA = 1440.0 / 25.4
MM_TO_UNIT = 96.0 / 25.4
PT_TO_UNIT = 96.0 / 72.0
DXA_TO_EMU = 635               # 1 dxa = 635 EMU

# допуски выравнивания сетки (в units)
XTOL = 3.0
YTOL = 6.0
GAP_SPLIT = 30.0               # пустая строка выше этого — разрыв таблицы + отступ

CONTAINERS = ("Band", "ReportPage")

NAMED_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "lime": "00FF00",
    "blue": "0000FF", "yellow": "FFFF00", "cyan": "00FFFF", "aqua": "00FFFF",
    "magenta": "FF00FF", "fuchsia": "FF00FF", "silver": "C0C0C0",
    "gray": "808080", "grey": "808080", "maroon": "800000", "olive": "808000",
    "green": "008000", "purple": "800080", "teal": "008080", "navy": "000080",
    "orange": "FFA500", "gold": "FFD700", "whitesmoke": "F5F5F5",
    "gainsboro": "DCDCDC", "lightgray": "D3D3D3", "lightgrey": "D3D3D3",
    "darkgray": "A9A9A9", "darkgrey": "A9A9A9", "beige": "F5F5DC",
    "ivory": "FFFFF0", "khaki": "F0E68C", "lavender": "E6E6FA",
    "lightblue": "ADD8E6", "lightgreen": "90EE90", "lightyellow": "FFFFE0",
    "pink": "FFC0CB", "brown": "A52A2A", "darkblue": "00008B",
    "darkgreen": "006400", "darkred": "8B0000", "transparent": None,
}

# RawPaperSize -> (ширина, высота) в мм
PAPER_SIZES = {
    1: (215.9, 279.4),    # Letter
    5: (215.9, 355.6),    # Legal
    8: (297.0, 420.0),    # A3
    9: (210.0, 297.0),    # A4
    11: (148.0, 210.0),   # A5
    13: (182.0, 257.0),   # B5
}

BORDER_STYLE_MAP = {
    "Solid": "single", "Dash": "dashed", "Dot": "dotted",
    "DashDot": "dashDotStroked", "DashDotDot": "dashDotStroked",
    "Double": "double",
}


def fnum(el, key, default=0.0) -> float:
    """Числовой атрибут XML-элемента с безопасным значением по умолчанию."""
    try:
        return float(el.attrib.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def parse_color(value):
    """'Red' | '255, 0, 0' | '#FFRRGGBB' | '#RRGGBB' -> 'RRGGBB' или None."""
    if not value:
        return None
    v = value.strip()
    low = v.lower()
    if low in NAMED_COLORS:
        return NAMED_COLORS[low]
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 8:
            return h[2:].upper()
        if len(h) == 6:
            return h.upper()
        return None
    if "," in v:
        parts = [p.strip() for p in v.split(",")]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None
        if len(nums) == 4:
            nums = nums[1:]
        if len(nums) == 3:
            return "%02X%02X%02X" % tuple(max(0, min(255, n)) for n in nums)
    return None


def format_color(rgb):
    """'RRGGBB' -> 'R, G, B' — так цвета пишет сам FastReport."""
    if not rgb:
        return None
    return "%d, %d, %d" % (int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16))


def parse_font(value):
    """'Arial, 9pt, style=Bold, Italic' -> dict."""
    res = {"name": "Arial", "size": 9.0, "bold": False,
           "italic": False, "underline": False, "strike": False}
    if not value:
        return res
    head, sep, style = value.partition("style=")
    parts = [p.strip() for p in head.split(",") if p.strip()]
    if parts:
        res["name"] = parts[0]
    for p in parts[1:]:
        m = re.match(r"^([\d.]+)\s*pt$", p)
        if m:
            res["size"] = float(m.group(1))
    if sep:
        res["bold"] = "Bold" in style
        res["italic"] = "Italic" in style
        res["underline"] = "Underline" in style
        res["strike"] = "Strikeout" in style
    return res


def format_font(font):
    """dict -> 'Arial, 9pt, style=Bold, Italic' для записи в .frx."""
    size = font.get("size", 9.0)
    size_txt = ("%g" % round(size, 2))
    out = "%s, %spt" % (font.get("name") or "Arial", size_txt)
    styles = [name for key, name in (("bold", "Bold"), ("italic", "Italic"),
                                     ("underline", "Underline"),
                                     ("strike", "Strikeout")) if font.get(key)]
    if styles:
        out += ", style=" + ", ".join(styles)
    return out


def parse_border(value):
    """Border.Lines -> {t,r,b,l} 0/1."""
    d = {"t": 0, "r": 0, "b": 0, "l": 0}
    if not value:
        return d
    if value.strip() == "All":
        return {"t": 1, "r": 1, "b": 1, "l": 1}
    for part in (x.strip() for x in value.split(",")):
        if part == "Left":
            d["l"] = 1
        elif part == "Right":
            d["r"] = 1
        elif part == "Top":
            d["t"] = 1
        elif part == "Bottom":
            d["b"] = 1
    return d


def format_border(brd):
    """{t,r,b,l} -> 'All' | 'Left, Top' | None (нет рамки)."""
    if not brd or not any(brd.values()):
        return None
    if all(brd.get(k) for k in "trbl"):
        return "All"
    names = [name for key, name in (("l", "Left"), ("r", "Right"),
                                    ("t", "Top"), ("b", "Bottom"))
             if brd.get(key)]
    return ", ".join(names)


def parse_padding(value):
    """Padding='l, t, r, b' в units -> кортеж из четырёх float."""
    if not value:
        return (2.0, 1.0, 2.0, 1.0)
    parts = [p.strip() for p in value.split(",")]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return (2.0, 1.0, 2.0, 1.0)
    if len(nums) == 4:
        return tuple(nums)
    if len(nums) == 1:
        return (nums[0],) * 4
    return (2.0, 1.0, 2.0, 1.0)


def object_fill(el):
    """Заливка: атрибут Fill.Color или дочерний <Fill Color=.../>.

    Градиент/штриховка/стекло приближаются первым (основным) цветом."""
    for key in ("Fill.Color", "Fill.StartColor", "Fill.BackColor",
                "Fill.ForeColor"):
        c = parse_color(el.attrib.get(key))
        if c:
            return c
    fill = el.find("Fill")
    if fill is not None:
        for key in ("Color", "StartColor", "BackColor", "ForeColor"):
            c = parse_color(fill.attrib.get(key))
            if c:
                return c
    return None


# --------------------------------------------------------------------------
# HTML-разметка внутри TextObject (TextRenderType="HtmlTags")
# --------------------------------------------------------------------------
HTML_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
                 "&quot;": '"', "&apos;": "'", "&#160;": " "}

TAG_RE = re.compile(r"<(/?)([a-zA-Z]+)([^>]*)>")
ATTR_RE = re.compile(r"""([a-zA-Z-]+)\s*=\s*["']?([^"'\s>]+)["']?""")


def unescape_entities(text):
    for k, v in HTML_ENTITIES.items():
        text = text.replace(k, v)
    return text


def escape_html(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def strip_html(text, enabled):
    if not enabled:
        return text
    text = re.sub(r"<br\s*/?>", "\r\n", text, flags=re.I)
    return unescape_entities(re.sub(r"<[^>]+>", "", text))


def blank_style():
    return {"bold": False, "italic": False, "underline": False,
            "strike": False, "size": None, "color": None, "face": None,
            "sub": False, "sup": False}


def parse_inline_html(text):
    """FastReport TextRenderType=HtmlTags: подмножество inline-разметки.
    Возвращает список строк, каждая — список фрагментов с оформлением."""
    lines = [[]]
    stack = []

    def style():
        st = blank_style()
        for tag, attrs in stack:
            if tag in ("b", "strong"):
                st["bold"] = True
            elif tag in ("i", "em"):
                st["italic"] = True
            elif tag == "u":
                st["underline"] = True
            elif tag in ("s", "strike", "del"):
                st["strike"] = True
            elif tag == "sub":
                st["sub"] = True
            elif tag == "sup":
                st["sup"] = True
            elif tag == "font":
                if "size" in attrs:
                    try:
                        st["size"] = float(attrs["size"])
                    except ValueError:
                        pass
                if "color" in attrs:
                    st["color"] = parse_color(attrs["color"])
                if "face" in attrs:
                    st["face"] = attrs["face"]
        return st

    def emit(chunk):
        if not chunk:
            return
        for i, part in enumerate(re.split(r"\r\n|\r|\n", chunk)):
            if i:
                lines.append([])
            if part:
                frag = dict(style())
                frag["text"] = unescape_entities(part)
                lines[-1].append(frag)

    pos = 0
    for m in TAG_RE.finditer(text):
        emit(text[pos:m.start()])
        pos = m.end()
        closing, name, rest = m.group(1), m.group(2).lower(), m.group(3)
        if name == "br":
            lines.append([])
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i]
                    break
        else:
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(rest)}
            stack.append((name, attrs))
    emit(text[pos:])
    return lines


def runs_to_html(lines):
    """Обратная операция: строки фрагментов -> разметка FastReport."""
    out = []
    for i, frags in enumerate(lines):
        if i:
            out.append("<br>")
        for frag in frags:
            body = escape_html(frag.get("text", ""))
            if not body:
                continue
            attrs = []
            if frag.get("face"):
                attrs.append('face="%s"' % frag["face"])
            if frag.get("size"):
                attrs.append('size="%g"' % frag["size"])
            if frag.get("color"):
                attrs.append('color="#%s"' % frag["color"])
            if attrs:
                body = "<font %s>%s</font>" % (" ".join(attrs), body)
            for flag, tag in (("strike", "s"), ("underline", "u"),
                              ("italic", "i"), ("bold", "b")):
                if frag.get(flag):
                    body = "<%s>%s</%s>" % (tag, body, tag)
            out.append(body)
    return "".join(out)


def split_lines(text):
    return re.split(r"\r\n|\r|\n", text or "")
