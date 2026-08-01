# -*- coding: utf-8 -*-
"""Чтение .pdf в модель документа.

PDF — формат абсолютного размещения, как и FastReport, поэтому текст берём
вместе с координатами: каждая строка становится TextObject там же, где она
была на листе. Соседние строки с одинаковым левым краем и шагом склеиваются
в абзац, чтобы шаблон было удобно править.

Разбор чисто питоновский: pdfparse.py достаёт объекты и потоки, здесь —
шрифты, интерпретация содержимого и группировка.
"""

from __future__ import annotations

import re

from . import doctree, pdfparse
from .common import PT_TO_UNIT
from .pdfparse import Name, Stream

SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.I)
ITALIC_RE = re.compile(r"italic|oblique", re.I)

# базовые кодировки для простых шрифтов
WIN_ANSI_EXTRA = {
    0x80: "€", 0x82: "‚", 0x83: "ƒ", 0x84: "„",
    0x85: "…", 0x86: "†", 0x87: "‡", 0x88: "ˆ",
    0x89: "‰", 0x8a: "Š", 0x8b: "‹", 0x8c: "Œ",
    0x8e: "Ž", 0x91: "‘", 0x92: "’", 0x93: "“",
    0x94: "”", 0x95: "•", 0x96: "–", 0x97: "—",
    0x98: "˜", 0x99: "™", 0x9a: "š", 0x9b: "›",
    0x9c: "œ", 0x9e: "ž", 0x9f: "Ÿ",
}


# --------------------------------------------------------------------------
# шрифты
# --------------------------------------------------------------------------
class PdfFont(object):
    def __init__(self, doc, node):
        self.doc = doc
        self.node = node or {}
        self.subtype = str(doc.get(self.node, "Subtype", "") or "")
        base = str(doc.get(self.node, "BaseFont", "") or "Helvetica")
        self.base = SUBSET_RE.sub("", base)
        self.family = self.base.split(",")[0].split("-")[0] or "Helvetica"
        self.bold = bool(BOLD_RE.search(base))
        self.italic = bool(ITALIC_RE.search(base))
        self.two_byte = self.subtype == "Type0"
        self.widths = {}
        self.default_width = 0.5
        self.to_unicode = {}
        self.encoding = {}
        self._load()

    def _load(self):
        doc = self.doc
        self._load_tounicode()
        if self.two_byte:
            self._load_cid()
        else:
            self._load_simple()
        descriptor = doc.get(self.node, "FontDescriptor")
        if isinstance(descriptor, dict):
            flags = int(doc.get(descriptor, "Flags", 0) or 0)
            if flags & 0x40000:
                self.bold = True
            if flags & 0x40:
                self.italic = True
            missing = doc.get(descriptor, "MissingWidth")
            if missing:
                self.default_width = float(missing) / 1000.0

    def _load_tounicode(self):
        stream = self.doc.get(self.node, "ToUnicode")
        if not isinstance(stream, Stream):
            return
        try:
            self.to_unicode = parse_cmap(stream.data(self.doc))
        except Exception:                                      # noqa: BLE001
            self.to_unicode = {}

    def _load_simple(self):
        doc = self.doc
        first = int(doc.get(self.node, "FirstChar", 0) or 0)
        widths = doc.get(self.node, "Widths")
        if isinstance(widths, list):
            for i, value in enumerate(widths):
                value = doc.resolve(value)
                if isinstance(value, (int, float)):
                    self.widths[first + i] = float(value) / 1000.0
        encoding = doc.get(self.node, "Encoding")
        differences = None
        base_name = ""
        if isinstance(encoding, Name):
            base_name = str(encoding)
        elif isinstance(encoding, dict):
            base_name = str(doc.get(encoding, "BaseEncoding", "") or "")
            differences = doc.get(encoding, "Differences")
        self.encoding = _base_encoding(base_name)
        if isinstance(differences, list):
            code = 0
            for item in differences:
                item = doc.resolve(item)
                if isinstance(item, (int, float)):
                    code = int(item)
                elif isinstance(item, Name):
                    self.encoding[code] = _glyph_char(str(item))
                    code += 1

    def _load_cid(self):
        doc = self.doc
        kids = doc.get(self.node, "DescendantFonts")
        child = doc.resolve(kids[0]) if isinstance(kids, list) and kids else None
        if not isinstance(child, dict):
            return
        self.default_width = float(doc.get(child, "DW", 1000) or 1000) / 1000.0
        array = doc.get(child, "W")
        if not isinstance(array, list):
            return
        index = 0
        while index < len(array):
            first = doc.resolve(array[index])
            if index + 1 >= len(array):
                break
            second = doc.resolve(array[index + 1])
            if isinstance(second, list):
                for k, value in enumerate(second):
                    value = doc.resolve(value)
                    if isinstance(value, (int, float)):
                        self.widths[int(first) + k] = float(value) / 1000.0
                index += 2
            else:
                if index + 2 < len(array):
                    value = doc.resolve(array[index + 2])
                    if isinstance(value, (int, float)):
                        for code in range(int(first), int(second) + 1):
                            self.widths[code] = float(value) / 1000.0
                index += 3

    def codes(self, raw):
        if self.two_byte:
            return [(raw[i] << 8) | (raw[i + 1] if i + 1 < len(raw) else 0)
                    for i in range(0, len(raw), 2)]
        return list(raw)

    def char(self, code):
        if code in self.to_unicode:
            return self.to_unicode[code]
        if not self.two_byte:
            if code in self.encoding:
                return self.encoding[code]
            if 32 <= code < 127:
                return chr(code)
            return WIN_ANSI_EXTRA.get(code, "")
        return ""

    def width(self, code):
        return self.widths.get(code, self.default_width)


def _base_encoding(name):
    table = {}
    for code in range(32, 127):
        table[code] = chr(code)
    if name in ("", "WinAnsiEncoding", "StandardEncoding", "PDFDocEncoding"):
        table.update(WIN_ANSI_EXTRA)
        for code in range(0xA0, 0x100):
            table[code] = chr(code)
    elif name == "MacRomanEncoding":
        for code in range(0x80, 0x100):
            try:
                table[code] = bytes([code]).decode("mac-roman")
            except Exception:                                  # noqa: BLE001
                pass
    return table


GLYPH_NAMES = {
    "space": " ", "quotesingle": "'", "quotedbl": '"', "hyphen": "-",
    "period": ".", "comma": ",", "colon": ":", "semicolon": ";",
    "numbersign": "#", "dollar": "$", "percent": "%", "ampersand": "&",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+",
    "slash": "/", "less": "<", "equal": "=", "greater": ">", "question": "?",
    "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]",
    "underscore": "_", "braceleft": "{", "bar": "|", "braceright": "}",
    "quoteleft": "‘", "quoteright": "’", "endash": "–",
    "emdash": "—", "bullet": "•", "quotedblleft": "“",
    "quotedblright": "”", "guillemotleft": "«",
    "guillemotright": "»", "nbspace": " ", "euro": "€",
}


def _glyph_char(name):
    if name in GLYPH_NAMES:
        return GLYPH_NAMES[name]
    m = re.match(r"^uni([0-9A-Fa-f]{4})$", name)
    if m:
        return chr(int(m.group(1), 16))
    m = re.match(r"^u([0-9A-Fa-f]{4,6})$", name)
    if m:
        return chr(int(m.group(1), 16))
    m = re.match(r"^(?:g|cid|c|index)(\d+)$", name)
    if m:
        return ""
    if len(name) == 1:
        return name
    return ""


CMAP_CHAR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>")
CMAP_RANGE_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
                           rb"(<[0-9A-Fa-f]*>|\[[^\]]*\])")


def parse_cmap(data):
    """ToUnicode CMap -> {код: строка}."""
    table = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in CMAP_CHAR_RE.findall(block):
            table[int(src, 16)] = _utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in CMAP_RANGE_RE.findall(block):
            start, end = int(lo, 16), int(hi, 16)
            if end - start > 65535:
                continue
            if dst.startswith(b"["):
                items = re.findall(rb"<([0-9A-Fa-f]*)>", dst)
                for i, item in enumerate(items):
                    table[start + i] = _utf16(item)
            else:
                base = dst.strip(b"<>")
                if not base:
                    continue
                value = int(base, 16)
                for i in range(end - start + 1):
                    table[start + i] = _utf16_value(value + i, len(base))
    return table


def _utf16(hex_bytes):
    if not hex_bytes:
        return ""
    raw = bytes.fromhex(hex_bytes.decode("ascii")
                        + ("0" if len(hex_bytes) % 2 else ""))
    try:
        return raw.decode("utf-16-be").replace("\x00", "")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _utf16_value(value, hex_len):
    if hex_len <= 4:
        return chr(value & 0xFFFF)
    return _utf16(("%0*X" % (hex_len, value)).encode("ascii"))


# --------------------------------------------------------------------------
# матрицы
# --------------------------------------------------------------------------
def mat_mul(m, n):
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


IDENTITY = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


# --------------------------------------------------------------------------
# интерпретатор содержимого
# --------------------------------------------------------------------------
class ContentReader(object):
    def __init__(self, doc, page, warnings):
        self.doc = doc
        self.page = page
        self.warnings = warnings
        self.items = []          # текст
        self.lines = []          # линии и рамки
        self.fonts = {}
        self._load_fonts()

    def _load_fonts(self):
        resources = self.doc.get(self.page, "Resources") or {}
        table = self.doc.get(resources, "Font") or {}
        if isinstance(table, dict):
            for key, value in table.items():
                try:
                    self.fonts[key] = PdfFont(self.doc, self.doc.resolve(value))
                except Exception as exc:                       # noqa: BLE001
                    self.warnings.append("шрифт %s не разобран: %s" % (key, exc))

    def run(self, data):
        parser = pdfparse.Parser(data)
        stack = []
        ctm = list(IDENTITY)
        graphics = []
        text = None
        state = {"font": None, "size": 12.0, "char": 0.0, "word": 0.0,
                 "scale": 1.0, "leading": 0.0, "rise": 0.0, "render": 0,
                 "fill": "000000", "stroke": "000000", "width": 1.0}
        path = []

        while True:
            token = parser.token()
            if token is None:
                break
            if isinstance(token, (bytes, Name)) or token in ("<<", "["):
                parser.pos -= 0
                stack.append(parser.value(token))
                continue
            if pdfparse.NUMBER_RE.match(token):
                stack.append(float(token))
                continue

            op = token
            args = stack
            stack = []
            try:
                if op == "q":
                    graphics.append((list(ctm), dict(state)))
                elif op == "Q" and graphics:
                    ctm, saved = graphics.pop()
                    ctm = list(ctm)
                    state = dict(saved)
                elif op == "cm" and len(args) >= 6:
                    ctm = mat_mul([float(a) for a in args[-6:]], ctm)
                elif op == "BT":
                    text = {"tm": list(IDENTITY), "tlm": list(IDENTITY)}
                elif op == "ET":
                    text = None
                elif op == "Tf" and len(args) >= 2:
                    state["font"] = self.fonts.get(str(args[-2]))
                    state["size"] = float(args[-1])
                elif op == "TL" and args:
                    state["leading"] = float(args[-1])
                elif op == "Tc" and args:
                    state["char"] = float(args[-1])
                elif op == "Tw" and args:
                    state["word"] = float(args[-1])
                elif op == "Tz" and args:
                    state["scale"] = float(args[-1]) / 100.0
                elif op == "Ts" and args:
                    state["rise"] = float(args[-1])
                elif op == "Tr" and args:
                    state["render"] = int(float(args[-1]))
                elif op == "Tm" and text is not None and len(args) >= 6:
                    text["tm"] = [float(a) for a in args[-6:]]
                    text["tlm"] = list(text["tm"])
                elif op in ("Td", "TD") and text is not None and len(args) >= 2:
                    if op == "TD":
                        state["leading"] = -float(args[-1])
                    text["tlm"] = mat_mul([1, 0, 0, 1, float(args[-2]),
                                           float(args[-1])], text["tlm"])
                    text["tm"] = list(text["tlm"])
                elif op == "T*" and text is not None:
                    text["tlm"] = mat_mul([1, 0, 0, 1, 0, -state["leading"]],
                                          text["tlm"])
                    text["tm"] = list(text["tlm"])
                elif op in ("Tj", "TJ", "'", '"') and text is not None:
                    if op in ("'", '"'):
                        if op == '"' and len(args) >= 3:
                            state["word"] = float(args[-3])
                            state["char"] = float(args[-2])
                        text["tlm"] = mat_mul([1, 0, 0, 1, 0,
                                               -state["leading"]], text["tlm"])
                        text["tm"] = list(text["tlm"])
                    payload = args[-1] if args else b""
                    self._show(payload, text, state, ctm)
                elif op in ("g", "rg", "k", "sc", "scn"):
                    state["fill"] = _color(args)
                elif op in ("G", "RG", "K", "SC", "SCN"):
                    state["stroke"] = _color(args)
                elif op == "w" and args:
                    state["width"] = float(args[-1])
                elif op == "re" and len(args) >= 4:
                    x, y, w, h = [float(a) for a in args[-4:]]
                    path.append([(x, y), (x + w, y), (x + w, y + h),
                                 (x, y + h), (x, y)])
                elif op == "m" and len(args) >= 2:
                    path.append([(float(args[-2]), float(args[-1]))])
                elif op == "l" and len(args) >= 2 and path:
                    path[-1].append((float(args[-2]), float(args[-1])))
                elif op in ("c", "v", "y") and path and len(args) >= 2:
                    path[-1].append((float(args[-2]), float(args[-1])))
                elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*"):
                    self._paint(path, ctm, state, op)
                    path = []
                elif op == "n":
                    path = []
                elif op == "Do":
                    pass
            except Exception:                                  # noqa: BLE001
                continue
        return self

    def _show(self, payload, text, state, ctm):
        font = state["font"]
        items = payload if isinstance(payload, list) else [payload]
        for chunk in items:
            if isinstance(chunk, (int, float)):
                shift = -float(chunk) / 1000.0 * state["size"] * state["scale"]
                text["tm"] = mat_mul([1, 0, 0, 1, shift, 0], text["tm"])
                continue
            if not isinstance(chunk, bytes) or font is None:
                continue
            combined = mat_mul(text["tm"], ctm)
            trm = mat_mul([state["size"] * state["scale"], 0, 0,
                           state["size"], 0, state["rise"]], combined)
            size = abs(state["size"] * _scale_y(combined))
            body = []
            advance = 0.0
            for code in font.codes(chunk):
                ch = font.char(code)
                body.append(ch)
                width = font.width(code) * state["size"] + state["char"]
                if code == 32 and not font.two_byte:
                    width += state["word"]
                advance += width * state["scale"]
            value = "".join(body)
            if value.strip() and state["render"] != 3:
                self.items.append({
                    "x": trm[4], "y": trm[5], "size": max(size, 1.0),
                    "text": value, "font": font,
                    "width": advance * abs(_scale_x(combined)),
                    "color": state["fill"],
                })
            text["tm"] = mat_mul([1, 0, 0, 1, advance, 0], text["tm"])

    # линейки в PDF рисуют и обводкой, и тонким закрашенным прямоугольником
    THIN = 1.6                      # до этой толщины (pt) считаем линией
    MIN_LENGTH = 3.0                # короче — это точка или засечка, не линия

    def _paint(self, path, ctm, state, op):
        filled = op.lower() in ("f", "f*", "b", "b*")
        color = state["fill"] if filled else state["stroke"]
        for points in path:
            if len(points) < 2:
                continue
            device = [_apply(ctm, p) for p in points]
            xs = [p[0] for p in device]
            ys = [p[1] for p in device]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if min(w, h) <= self.THIN:
                if max(w, h) < self.MIN_LENGTH:
                    continue
                self.lines.append({"x": min(xs), "y": min(ys), "w": w, "h": h,
                                   "color": color,
                                   "width": max(min(w, h), state["width"], 0.4)})
            elif not filled and len(points) >= 5:
                self.lines.append({"x": min(xs), "y": min(ys), "w": w, "h": h,
                                   "color": color,
                                   "width": max(state["width"], 0.4),
                                   "rect": True})


def merge_lines(lines, tolerance=1.2):
    """Word рвёт рамку на куски — собираем соседние отрезки обратно."""
    rects = [l for l in lines if l.get("rect")]
    rest = [l for l in lines if not l.get("rect")]
    out = list(rects)
    for horizontal in (True, False):
        groups = {}
        for line in rest:
            if (line["w"] >= line["h"]) != horizontal:
                continue
            key = (round(line["y"] if horizontal else line["x"], 0),
                   line["color"])
            groups.setdefault(key, []).append(line)
        for items in groups.values():
            axis = "x" if horizontal else "y"
            size = "w" if horizontal else "h"
            items.sort(key=lambda l: l[axis])
            current = dict(items[0])
            for line in items[1:]:
                end = current[axis] + current[size]
                if line[axis] <= end + tolerance:
                    new_end = max(end, line[axis] + line[size])
                    current[size] = new_end - current[axis]
                    current["width"] = max(current["width"], line["width"])
                else:
                    out.append(current)
                    current = dict(line)
            out.append(current)
    return out


def _apply(m, point):
    x, y = point
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _scale_x(m):
    return (m[0] ** 2 + m[1] ** 2) ** 0.5 or 1.0


def _scale_y(m):
    return (m[2] ** 2 + m[3] ** 2) ** 0.5 or 1.0


def _color(args):
    values = [float(a) for a in args if isinstance(a, (int, float))]
    if len(values) == 1:
        level = int(max(0.0, min(1.0, values[0])) * 255)
        return "%02X%02X%02X" % (level, level, level)
    if len(values) == 3:
        return "%02X%02X%02X" % tuple(int(max(0.0, min(1.0, v)) * 255)
                                      for v in values)
    if len(values) == 4:
        c, m, y, k = values
        return "%02X%02X%02X" % tuple(
            int(255 * max(0.0, min(1.0, (1 - v) * (1 - k))))
            for v in (c, m, y))
    return "000000"


# --------------------------------------------------------------------------
# группировка
# --------------------------------------------------------------------------
def group_lines(items):
    """Слова -> строки: одинаковая базовая линия, слева направо."""
    lines = []
    for item in sorted(items, key=lambda i: (-round(i["y"], 1), i["x"])):
        placed = False
        for line in lines:
            if abs(line["y"] - item["y"]) <= max(1.2, line["size"] * 0.28):
                line["items"].append(item)
                line["size"] = max(line["size"], item["size"])
                placed = True
                break
        if not placed:
            lines.append({"y": item["y"], "size": item["size"],
                          "items": [item]})
    for line in lines:
        line["items"].sort(key=lambda i: i["x"])
    lines.sort(key=lambda l: -l["y"])
    return lines


def split_segments(line):
    """Строка -> куски, разделённые заметными пробелами (колонки листа)."""
    segments = []
    current = None
    for item in line["items"]:
        if current is None:
            current = {"items": [item], "x": item["x"],
                       "end": item["x"] + item["width"]}
            continue
        gap = item["x"] - current["end"]
        if gap > item["size"] * 1.2:
            segments.append(current)
            current = {"items": [item], "x": item["x"],
                       "end": item["x"] + item["width"]}
        else:
            current["items"].append(item)
            current["end"] = max(current["end"], item["x"] + item["width"])
    if current:
        segments.append(current)
    return segments


def segment_runs(segment):
    runs = []
    previous_end = None
    for item in segment["items"]:
        text = item["text"]
        if previous_end is not None:
            gap = item["x"] - previous_end
            if gap > item["size"] * 0.16 and not text.startswith(" "):
                text = " " + text
        previous_end = item["x"] + item["width"]
        font = item["font"]
        runs.append(doctree.run(
            text, bold=font.bold, italic=font.italic,
            size=round(item["size"], 1), face=_family(font),
            color=None if item["color"] in ("000000", None) else item["color"]))
    return _merge_runs(runs)


def _family(font):
    name = font.family
    known = {"Helvetica": "Arial", "TimesNewRomanPSMT": "Times New Roman",
             "TimesNewRomanPS": "Times New Roman", "Times": "Times New Roman",
             "Courier": "Courier New", "ArialMT": "Arial"}
    name = known.get(name, name)
    return re.sub(r"(MT|PSMT|PS)$", "", name) or "Arial"


def _merge_runs(runs):
    out = []
    for frag in runs:
        if out and all(out[-1][k] == frag[k] for k in
                       ("bold", "italic", "size", "face", "color")):
            out[-1]["text"] += frag["text"]
        else:
            out.append(dict(frag))
    return out


def merge_paragraphs(rows):
    """Соседние одиночные строки с общим левым краем -> один абзац.

    Первая строка абзаца часто с красной строкой, поэтому левый край
    задаётся второй строкой, а первой разрешено быть правее."""
    blocks = []
    index = 0
    while index < len(rows):
        row = rows[index]
        group = [row]
        if len(row["segments"]) == 1:
            left = None
            while index + 1 < len(rows):
                nxt = rows[index + 1]
                if len(nxt["segments"]) != 1:
                    break
                gap = group[-1]["y"] - nxt["y"]
                if not 0.6 * row["size"] < gap < 1.9 * row["size"]:
                    break
                if abs(nxt["size"] - row["size"]) > 0.6:
                    break
                x = nxt["segments"][0]["x"]
                if left is None:
                    # красная строка: первая строка правее остальных
                    indent = group[0]["segments"][0]["x"] - x
                    if not (abs(indent) <= 2.0 or 0 < indent <= 60.0):
                        break
                    left = x
                elif abs(x - left) > 2.0:
                    break
                group.append(nxt)
                index += 1
        blocks.append(group)
        index += 1
    return blocks


# --------------------------------------------------------------------------
def read_pdf(path, warnings):
    doc = pdfparse.load(path)
    pages = doc.pages()
    if not pages:
        raise ValueError("в PDF не найдено ни одной страницы")

    out = doctree.document()
    for number, page in enumerate(pages, start=1):
        try:
            out["sections"].append(_page_section(doc, page, warnings))
        except Exception as exc:                               # noqa: BLE001
            warnings.append("страница %d не разобрана: %s" % (number, exc))
    if not out["sections"]:
        raise ValueError("не удалось разобрать ни одной страницы PDF")
    return out


def _page_section(doc, page, warnings):
    box = doc.get(page, "MediaBox") or [0, 0, 595.276, 841.89]
    box = [float(doc.resolve(v)) for v in box]
    x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), \
        max(box[0], box[2]), max(box[1], box[3])
    width_pt, height_pt = x1 - x0, y1 - y0
    rotate = int(doc.get(page, "Rotate", 0) or 0) % 360

    reader = ContentReader(doc, page, warnings).run(doc.content(page))

    section = doctree.section(
        width=width_pt * PT_TO_UNIT, height=height_pt * PT_TO_UNIT,
        margins={"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0})
    if rotate in (90, 270):
        section["width"], section["height"] = section["height"], section["width"]
        section["landscape"] = width_pt < height_pt

    def to_page(x, y):
        """PDF-координаты -> координаты листа сверху вниз, в units."""
        px, py = x - x0, y - y0
        if rotate == 90:                      # лист повёрнут по часовой
            dx, dy = py, px
        elif rotate == 180:
            dx, dy = width_pt - px, py
        elif rotate == 270:
            dx, dy = height_pt - py, width_pt - px
        else:
            dx, dy = px, height_pt - py
        return dx * PT_TO_UNIT, dy * PT_TO_UNIT

    rows = []
    for line in group_lines(reader.items):
        segments = split_segments(line)
        rows.append({"y": line["y"], "size": line["size"],
                     "segments": segments})

    body = []
    for group in merge_paragraphs(rows):
        if len(group) == 1:
            for segment in group[0]["segments"]:
                body.append(_segment_block(segment, group[0], to_page))
        else:
            body.append(_paragraph_block(group, to_page))

    for shape in merge_lines(reader.lines):
        body.append(_shape_block(shape, to_page))

    section["body"] = body
    return section


def _segment_block(segment, row, to_page):
    runs = segment_runs(segment)
    size = row["size"]
    x, y = to_page(segment["x"], row["y"] + size * 0.78)
    width = max((segment["end"] - segment["x"]) * PT_TO_UNIT, 6.0)
    height = size * 1.25 * PT_TO_UNIT
    return {"type": "abs", "x": round(x, 2), "y": round(y, 2),
            "w": round(width + 4, 2), "h": round(height, 2),
            "runs": runs, "align": "Left", "valign": "Top"}


def _paragraph_block(group, to_page):
    runs = []
    left = min(row["segments"][0]["x"] for row in group)
    right = max(row["segments"][0]["end"] for row in group)
    for index, row in enumerate(group):
        if index:
            runs.append(doctree.run("\n"))
        runs.extend(segment_runs(row["segments"][0]))
    size = max(row["size"] for row in group)
    first = group[0]
    x, y = to_page(left, first["y"] + size * 0.78)
    height = (group[0]["y"] - group[-1]["y"] + size * 1.25) * PT_TO_UNIT
    indent = (first["segments"][0]["x"] - left) * PT_TO_UNIT
    block = {"type": "abs", "x": round(x, 2), "y": round(y, 2),
             "w": round((right - left) * PT_TO_UNIT + 4, 2),
             "h": round(height, 2), "runs": _merge_runs(runs),
             "align": "Left", "valign": "Top"}
    if indent > 2:
        block["indent"] = round(indent, 2)
    return block


def _shape_block(shape, to_page):
    x, y = to_page(shape["x"], shape["y"] + shape["h"])
    width = max(shape["w"] * PT_TO_UNIT, 1.0)
    height = max(shape["h"] * PT_TO_UNIT, 1.0)
    if shape.get("rect"):
        borders = {"t": 1, "r": 1, "b": 1, "l": 1}
    elif shape["w"] >= shape["h"]:
        borders = {"t": 1, "r": 0, "b": 0, "l": 0}
    else:
        borders = {"t": 0, "r": 0, "b": 0, "l": 1}
    return {"type": "abs", "x": round(x, 2), "y": round(y, 2),
            "w": round(width, 2), "h": round(height, 2),
            "runs": [doctree.run("")], "align": "Left", "valign": "Top",
            "borders": borders, "border_color": shape["color"],
            "border_width": max(shape["width"] * PT_TO_UNIT, 0.5)}
