# -*- coding: utf-8 -*-
"""RTF <-> размеченный текст. Используется для RichObject.

rtf_to_lines() сохраняет начертание, размер, цвет и шрифт каждого фрагмента,
а также выравнивание абзаца. rtf_to_text() — тот же разбор, но плоским текстом.
lines_to_rtf() собирает RTF обратно, чтобы обратный конвертер мог положить
форматированный текст в RichObject.
"""

from __future__ import annotations

import re

from .common import blank_style

# служебные группы, содержимое которых в текст не идёт
RTF_SKIP_DESTINATIONS = {
    "fonttbl", "colortbl", "stylesheet", "info", "generator", "pict",
    "listtable", "listoverridetable", "rsidtbl", "themedata", "datastore",
    "xmlnstbl", "latentstyles", "filetbl", "revtbl", "author", "operator",
    "company", "creatim", "revtim", "printim", "buptim", "doccomm", "title",
    "subject", "keywords", "category", "comment", "manager", "userprops",
    "colorschememapping", "mmathPr", "wgrffmtfilter", "panose", "falt",
}

CTRL_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")
ALIGN_WORDS = {"ql": "Left", "qr": "Right", "qc": "Center", "qj": "Justify"}


def _is_rtf(text):
    return bool(text) and text.lstrip().startswith("{\\rtf")


def _codec_of(rtf):
    m = re.search(r"\\ansicpg(\d+)", rtf)
    codec = "cp%s" % m.group(1) if m else "cp1252"
    try:
        "".encode(codec)
    except LookupError:
        codec = "cp1252"
    return codec


def _font_table(rtf):
    """Номер шрифта -> имя, из группы {\\fonttbl ...}."""
    table = {}
    start = rtf.find("{\\fonttbl")
    if start < 0:
        return table
    depth, i = 0, start
    while i < len(rtf):
        if rtf[i] == "{":
            depth += 1
        elif rtf[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    chunk = rtf[start:i + 1]
    for m in re.finditer(r"\\f(\d+)[^;}]*?[ ]([^;}\\]+);", chunk):
        table[int(m.group(1))] = m.group(2).strip()
    return table


def _color_table(rtf):
    """Индекс цвета -> 'RRGGBB'. Нулевой индекс в RTF — «цвет по умолчанию»."""
    m = re.search(r"\{\\colortbl([^}]*)\}", rtf)
    if not m:
        return {}
    colors = {}
    for idx, item in enumerate(m.group(1).split(";")[:-1]):
        r = re.search(r"\\red(\d+)", item)
        g = re.search(r"\\green(\d+)", item)
        b = re.search(r"\\blue(\d+)", item)
        if r and g and b:
            colors[idx] = "%02X%02X%02X" % (int(r.group(1)), int(g.group(1)),
                                            int(b.group(1)))
    return colors


def rtf_to_lines(rtf: str, base_size=None):
    """RTF -> (строки фрагментов, выравнивание первого абзаца).

    Строка — список словарей {text, bold, italic, underline, strike,
    size, color, face}. Формат совпадает с parse_inline_html()."""
    if not _is_rtf(rtf):
        text = rtf or ""
        return [[dict(blank_style(), text=ln)] if ln else []
                for ln in re.split(r"\r\n|\r|\n", text)], None

    codec = _codec_of(rtf)
    fonts = _font_table(rtf)
    colors = _color_table(rtf)

    state = {"bold": False, "italic": False, "underline": False,
             "strike": False, "size": base_size, "color": None, "face": None}
    stack = []
    lines = [[]]
    align = None
    align_seen = False
    pending = bytearray()
    skip_depth = None
    depth = 0
    ucskip = 1
    i, n = 0, len(rtf)

    def flush():
        if not pending:
            return
        chunk = pending.decode(codec, errors="replace")
        pending.clear()
        add_text(chunk)

    def add_text(chunk):
        if not chunk:
            return
        frag = dict(blank_style())
        frag.update({k: state[k] for k in
                     ("bold", "italic", "underline", "strike", "size",
                      "color", "face")})
        frag["text"] = chunk
        last = lines[-1]
        if last and _same_style(last[-1], frag):
            last[-1]["text"] += chunk
        else:
            last.append(frag)

    def newline():
        flush()
        lines.append([])

    while i < n:
        ch = rtf[i]
        if ch == "\\":
            m = CTRL_RE.match(rtf, i)
            if m:
                word, param = m.group(1), m.group(2)
                i = m.end()
                if skip_depth is not None:
                    continue
                if word in ("par", "line", "sect", "row"):
                    newline()
                elif word == "tab":
                    flush()
                    add_text("\t")
                elif word == "uc":
                    ucskip = int(param) if param else 1
                elif word == "u":
                    flush()
                    code = int(param) if param else 0
                    if code < 0:
                        code += 65536
                    add_text(chr(code))
                    skipped = 0
                    while skipped < ucskip and i < n:
                        if rtf[i:i + 2] == "\\'":
                            i += 4
                        else:
                            i += 1
                        skipped += 1
                elif word == "b":
                    flush()
                    state["bold"] = param != "0"
                elif word == "i":
                    flush()
                    state["italic"] = param != "0"
                elif word in ("ul", "ulw", "uld", "uldb"):
                    flush()
                    state["underline"] = param != "0"
                elif word == "ulnone":
                    flush()
                    state["underline"] = False
                elif word == "strike":
                    flush()
                    state["strike"] = param != "0"
                elif word == "fs" and param:
                    flush()
                    state["size"] = int(param) / 2.0
                elif word == "cf" and param is not None:
                    flush()
                    state["color"] = colors.get(int(param))
                elif word == "f" and param is not None:
                    flush()
                    state["face"] = fonts.get(int(param)) or state["face"]
                elif word == "plain":
                    flush()
                    state.update({"bold": False, "italic": False,
                                  "underline": False, "strike": False})
                elif word in ALIGN_WORDS:
                    if not align_seen:
                        align = ALIGN_WORDS[word]
                        align_seen = True
                elif word in RTF_SKIP_DESTINATIONS:
                    skip_depth = depth
                continue
            nxt = rtf[i + 1] if i + 1 < n else ""
            if nxt == "'":
                try:
                    pending.append(int(rtf[i + 2:i + 4], 16))
                except ValueError:
                    pass
                i += 4
                continue
            if nxt == "*":
                i += 2
                if skip_depth is None:
                    skip_depth = depth
                continue
            if nxt in ("\\", "{", "}"):
                if skip_depth is None:
                    flush()
                    add_text(nxt)
                i += 2
                continue
            i += 1
            continue
        if ch == "{":
            depth += 1
            if skip_depth is None:
                flush()
                stack.append(dict(state))
            i += 1
            continue
        if ch == "}":
            depth -= 1
            if skip_depth is not None and depth < skip_depth:
                skip_depth = None
            elif skip_depth is None:
                flush()
                if stack:
                    state.update(stack.pop())
            i += 1
            continue
        if ch in "\r\n":
            i += 1
            continue
        if skip_depth is None:
            pending.extend(ch.encode(codec, errors="replace"))
        i += 1
    flush()

    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines or [[]], align


def _same_style(a, b):
    return all(a.get(k) == b.get(k) for k in
               ("bold", "italic", "underline", "strike", "size", "color",
                "face"))


def rtf_to_text(rtf: str) -> str:
    """Плоский текст из RTF."""
    if not _is_rtf(rtf):
        return rtf or ""
    lines, _ = rtf_to_lines(rtf)
    return "\r\n".join("".join(f["text"] for f in ln) for ln in lines).strip()


# --------------------------------------------------------------------------
# сборка RTF (обратный путь)
# --------------------------------------------------------------------------
def _rtf_escape(text):
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("\\u%d?" % ord(ch))
    return "".join(out)


def lines_to_rtf(lines, align=None, default_font="Times New Roman",
                 default_size=10.0):
    """Строки фрагментов -> RTF для RichObject."""
    faces, colors = [default_font], ["000000"]
    for line in lines:
        for frag in line:
            face = frag.get("face") or default_font
            if face not in faces:
                faces.append(face)
            color = frag.get("color")
            if color and color not in colors:
                colors.append(color)

    parts = ["{\\rtf1\\ansi\\ansicpg1251\\deff0"]
    parts.append("{\\fonttbl" + "".join(
        "{\\f%d\\fnil\\fcharset204 %s;}" % (i, f) for i, f in enumerate(faces))
        + "}")
    parts.append("{\\colortbl ;" + "".join(
        "\\red%d\\green%d\\blue%d;" % (int(c[0:2], 16), int(c[2:4], 16),
                                       int(c[4:6], 16)) for c in colors[1:])
        + "}")
    align_word = {"Center": "\\qc", "Right": "\\qr",
                  "Justify": "\\qj"}.get(align, "\\ql")

    for i, line in enumerate(lines):
        if i:
            parts.append("\\par")
        parts.append("\\pard%s" % align_word)
        for frag in line:
            ctrl = []
            if frag.get("bold"):
                ctrl.append("\\b")
            if frag.get("italic"):
                ctrl.append("\\i")
            if frag.get("underline"):
                ctrl.append("\\ul")
            if frag.get("strike"):
                ctrl.append("\\strike")
            face = frag.get("face") or default_font
            ctrl.append("\\f%d" % faces.index(face))
            ctrl.append("\\fs%d" % int(round((frag.get("size")
                                              or default_size) * 2)))
            color = frag.get("color")
            if color:
                ctrl.append("\\cf%d" % colors.index(color))
            parts.append("{%s %s}" % ("".join(ctrl),
                                      _rtf_escape(frag.get("text", ""))))
    parts.append("}")
    return "".join(parts)
