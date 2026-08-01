# -*- coding: utf-8 -*-
"""Встроенный движок PDF: сетка блоков -> .pdf без Word и LibreOffice.

Рисуем из той же модели, что и docx (layout.gridify), поэтому обе выдачи
согласованы. Шрифты берём системные TrueType и встраиваем целиком как
CIDFontType2 с кодировкой Identity-H — кириллица работает без оговорок.
"""

from __future__ import annotations

import base64
import zlib

from . import fonts, pdfimage
from .common import UNIT_TO_PT, split_lines
from .layout import page_blocks, part_blocks

DXA_TO_PT = 1.0 / 20.0


# --------------------------------------------------------------------------
# контейнер PDF
# --------------------------------------------------------------------------
class Pdf(object):
    def __init__(self):
        self.objects = [None]          # индексация с единицы

    def reserve(self):
        self.objects.append(None)
        return len(self.objects) - 1

    def put(self, num, data):
        self.objects[num] = data

    def add(self, data):
        num = self.reserve()
        self.put(num, data)
        return num

    def add_stream(self, dict_body, payload, compress=True):
        if compress:
            payload = zlib.compress(payload, 9)
            dict_body = dict_body.rstrip() + " /Filter /FlateDecode"
        head = "<< %s /Length %d >>\nstream\n" % (dict_body, len(payload))
        return self.add(head.encode("latin-1") + payload + b"\nendstream")

    def save(self, path, root, info=None):
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * len(self.objects)
        for num in range(1, len(self.objects)):
            body = self.objects[num]
            if body is None:
                body = b"null"
            if isinstance(body, str):
                body = body.encode("latin-1")
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n" % len(self.objects)
        out += b"0000000000 65535 f \n"
        for num in range(1, len(self.objects)):
            out += b"%010d 00000 n \n" % offsets[num]
        trailer = "trailer\n<< /Size %d /Root %d 0 R" % (len(self.objects), root)
        if info:
            trailer += " /Info %d 0 R" % info
        trailer += " >>\nstartxref\n%d\n%%%%EOF\n" % xref
        out += trailer.encode("latin-1")
        with open(path, "wb") as fh:
            fh.write(bytes(out))


def pdf_string(text):
    """Текст в кодировке PDFDocEncoding/UTF-16 для метаданных."""
    try:
        text.encode("latin-1")
        body = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        return "(%s)" % body
    except UnicodeEncodeError:
        return "<FEFF%s>" % text.encode("utf-16-be").hex().upper()


# --------------------------------------------------------------------------
# шрифты
# --------------------------------------------------------------------------
class FontPool(object):
    # чем добираем символы, которых нет в основном шрифте (галки, стрелки)
    FALLBACKS = ("Segoe UI Symbol", "Segoe UI Historic", "Arial Unicode MS",
                 "DejaVu Sans", "Segoe UI")

    def __init__(self, warnings):
        self.entries = {}
        self.warnings = warnings
        self.missing = set()

    def covers(self, entry, ch):
        font = entry["font"]
        if font is None:
            return True
        if ch in " \t\r\n":
            return True
        return font.gid(ch) != 0

    def split_by_coverage(self, entry, text, bold=False, italic=False):
        """Текст -> [(шрифт, кусок)] — символы вне основного шрифта уходят
        в запасной, иначе в PDF был бы пустой прямоугольник."""
        chunks = []
        for ch in text:
            target = entry
            if not self.covers(entry, ch):
                target = self._fallback_for(ch, bold, italic) or entry
            if chunks and chunks[-1][0] is target:
                chunks[-1][1] += ch
            else:
                chunks.append([target, ch])
        return chunks or [[entry, ""]]

    def _fallback_for(self, ch, bold, italic):
        for family in self.FALLBACKS:
            entry = self.use(family, bold, italic)
            if entry["font"] is not None and self.covers(entry, ch):
                return entry
        return None

    def use(self, family, bold=False, italic=False):
        key = ((family or "Arial").lower(), bool(bold), bool(italic))
        entry = self.entries.get(key)
        if entry:
            return entry
        if family and not fonts.have(family) and key[0] not in self.missing:
            self.missing.add(key[0])
            self.warnings.append("шрифт %s в системе не найден — взята замена"
                                 % family)
        font = fonts.load(family, bold, italic)
        if font is not None:              # один файл — одна запись в PDF
            for existing in list(self.entries.values()):
                if (existing["font"] is not None
                        and existing["font"].path == font.path):
                    self.entries[key] = existing
                    return existing
        entry = {"name": "F%d" % (len(self.entries) + 1), "font": font,
                 "used": {0}, "family": family or "Arial",
                 "bold": bold, "italic": italic}
        self.entries[key] = entry
        return entry

    def encode(self, entry, text):
        """Строка -> шестнадцатеричный литерал Identity-H."""
        font = entry["font"]
        out = []
        for ch in text:
            gid = font.gid(ch) if font else 0
            entry["used"].add(gid)
            entry.setdefault("tounicode", {})[gid] = ch
            out.append("%04X" % gid)
        return "<%s>" % "".join(out)

    def width(self, entry, text, size):
        font = entry["font"]
        if font is None:
            return len(text) * size * 0.5
        return font.text_width(text, size)

    def line_height(self, entry):
        font = entry["font"]
        return font.line_height if font else 1.15

    def ascent(self, entry):
        font = entry["font"]
        return (font.ascent / float(font.units_per_em)) if font else 0.9

    def emit(self, pdf):
        """Все использованные шрифты -> объекты PDF. Возвращает /Font dict."""
        parts, seen = [], set()
        for entry in self.entries.values():
            if id(entry) in seen or entry["font"] is None:
                continue
            seen.add(id(entry))
            parts.append("/%s %d 0 R" % (entry["name"], _emit_font(pdf, entry)))
        return "<< %s >>" % " ".join(parts) if parts else "<< >>"


def _emit_font(pdf, entry):
    font = entry["font"]
    scale = 1000.0 / font.units_per_em
    base = _ps_name(entry)

    try:
        blob = font.subset(entry["used"])
    except Exception:                                          # noqa: BLE001
        blob = font.data                        # не вышло — встроим целиком
    file_ref = pdf.add_stream("/Length1 %d" % len(blob), blob)
    descriptor = pdf.add(
        "<< /Type /FontDescriptor /FontName /%s /Flags %d "
        "/FontBBox [%d %d %d %d] /ItalicAngle %g /Ascent %d /Descent %d "
        "/CapHeight %d /StemV %d /FontFile2 %d 0 R >>"
        % (base, font.flags,
           int(font.bbox[0] * scale), int(font.bbox[1] * scale),
           int(font.bbox[2] * scale), int(font.bbox[3] * scale),
           font.italic_angle, int(font.ascent * scale),
           int(font.descent * scale), int(font.cap_height * scale),
           font.stem_v, file_ref))

    widths = []
    for gid in sorted(entry["used"]):
        widths.append("%d [%d]" % (gid, int(round(font.advance(gid) * scale))))
    cid_font = pdf.add(
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /%s "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        "/Supplement 0 >> /FontDescriptor %d 0 R /DW 1000 /W [%s] "
        "/CIDToGIDMap /Identity >>" % (base, descriptor, " ".join(widths)))

    to_unicode = pdf.add_stream("", _tounicode_cmap(entry).encode("latin-1"))
    return pdf.add(
        "<< /Type /Font /Subtype /Type0 /BaseFont /%s /Encoding /Identity-H "
        "/DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>"
        % (base, cid_font, to_unicode))


def _ps_name(entry):
    """Имя шрифта для PDF. Только ASCII: имя семейства в шаблоне вполне может
    быть кириллическим, а тело объекта PDF пишется в latin-1."""
    name = "".join(ch for ch in entry["family"] if ch.isascii() and ch.isalnum())
    if not name:
        name = "Font" + entry["name"]        # F1, F2 — заодно уникально
    if entry["bold"]:
        name += "Bold"
    if entry["italic"]:
        name += "Italic"
    return name


CMAP_HEAD = """/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
"""


def _tounicode_cmap(entry):
    items = [(gid, ch) for gid, ch in entry.get("tounicode", {}).items() if gid]
    items.sort()
    out = [CMAP_HEAD]
    for start in range(0, len(items), 100):
        chunk = items[start:start + 100]
        out.append("%d beginbfchar\n" % len(chunk))
        for gid, ch in chunk:
            out.append("<%04X> <%s>\n"
                       % (gid, ch.encode("utf-16-be").hex().upper()))
        out.append("endbfchar\n")
    out.append("endcmap\nCMapName currentdict /CMap defineresource pop\n"
               "end\nend\n")
    return "".join(out)


# --------------------------------------------------------------------------
# холст страницы
# --------------------------------------------------------------------------
class Canvas(object):
    def __init__(self, width_pt, height_pt, pool, images):
        self.width = width_pt
        self.height = height_pt
        self.pool = pool
        self.images = images
        self.ops = []
        self.used_fonts = set()
        self.used_images = set()

    # координаты: вход — от левого верхнего угла страницы
    def _y(self, y):
        return self.height - y

    def rect_fill(self, x, y, w, h, color):
        r, g, b = _rgb(color)
        self.ops.append("%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f"
                        % (r, g, b, x, self._y(y + h), w, h))

    def line(self, x1, y1, x2, y2, width, color, style="Solid"):
        r, g, b = _rgb(color)
        dash = {"Dash": "[3 2] 0", "Dot": "[1 2] 0",
                "DashDot": "[3 2 1 2] 0", "DashDotDot": "[3 2 1 2 1 2] 0"}
        self.ops.append("q %.3f %.3f %.3f RG %.2f w %s"
                        % (r, g, b, max(width, 0.1),
                           "%s d" % dash[style] if style in dash else "[] 0 d"))
        self.ops.append("%.2f %.2f m %.2f %.2f l S Q"
                        % (x1, self._y(y1), x2, self._y(y2)))

    def text(self, x, y, entry, size, text, color="000000", angle=0):
        if not text:
            return
        self.used_fonts.add(entry["name"])
        r, g, b = _rgb(color)
        payload = self.pool.encode(entry, text)
        py = self._y(y)
        if angle == 90:
            matrix = "0 1 -1 0 %.2f %.2f" % (x, py)
        elif angle == 270:
            matrix = "0 -1 1 0 %.2f %.2f" % (x, py)
        elif angle == 180:
            matrix = "-1 0 0 -1 %.2f %.2f" % (x, py)
        else:
            matrix = "1 0 0 1 %.2f %.2f" % (x, py)
        self.ops.append("BT %.3f %.3f %.3f rg /%s %.2f Tf %s Tm %s Tj ET"
                        % (r, g, b, entry["name"], size, matrix, payload))

    def image(self, name, x, y, w, h):
        self.used_images.add(name)
        self.ops.append("q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q"
                        % (w, h, x, self._y(y + h), name))

    def content(self):
        return "\n".join(self.ops).encode("latin-1")


def _rgb(color):
    if not color:
        return 0.0, 0.0, 0.0
    return (int(color[0:2], 16) / 255.0, int(color[2:4], 16) / 255.0,
            int(color[4:6], 16) / 255.0)


# --------------------------------------------------------------------------
# отрисовка ячейки
# --------------------------------------------------------------------------
ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT, ALIGN_JUSTIFY = range(4)
ALIGN_CODE = {"Left": ALIGN_LEFT, "Center": ALIGN_CENTER,
              "Right": ALIGN_RIGHT, "Justify": ALIGN_JUSTIFY}


# системные переменные FastReport: во встроенном движке их значения известны
PAGE_CONTEXT = {"page": 1, "total": 1}
FIELD_KEYS = {"[Page]": "page", "[Page#]": "page",
              "[TotalPages]": "total", "[TotalPages#]": "total"}


def substitute_fields(text):
    if "[" not in text:
        return text
    for token, key in FIELD_KEYS.items():
        if token in text:
            text = text.replace(token, str(PAGE_CONTEXT[key]))
    return text


def cell_lines(obj, pool, width_pt):
    """Готовые к печати строки: [(фрагменты, последняя ли в абзаце)]."""
    base = obj["font"]
    if obj.get("runs"):
        source = obj["runs"]
    else:
        source = [[{"text": ln}] for ln in split_lines(obj["text"])]

    result = []
    for frags in source:
        pieces = []
        for frag in frags:
            bold = bool(frag.get("bold") or base["bold"])
            italic = bool(frag.get("italic") or base["italic"])
            entry = pool.use(frag.get("face") or base["name"], bold, italic)
            body = substitute_fields(frag.get("text", ""))
            for target, chunk in pool.split_by_coverage(entry, body,
                                                        bold, italic):
                pieces.append({
                    "text": chunk, "entry": target,
                    "size": frag.get("size") or base["size"],
                    "color": frag.get("color") or obj.get("color") or "000000",
                    "underline": bool(frag.get("underline")
                                      or base["underline"]),
                    "strike": bool(frag.get("strike") or base["strike"]),
                })
        if not pieces:
            result.append(([], True))
            continue
        if obj.get("wrap", True):
            result.extend(_wrap_pieces(pieces, pool, width_pt))
        else:
            result.append((pieces, True))
    return result


def _wrap_pieces(pieces, pool, width_pt):
    """Перенос по словам с сохранением оформления каждого куска."""
    words = []
    for piece in pieces:
        for token in fonts._split_words(piece["text"]):
            words.append(dict(piece, text=token))
    if not words:
        return [([], True)]

    lines, current, used = [], [], 0.0
    for word in words:
        w = pool.width(word["entry"], word["text"], word["size"])
        if current and used + w > width_pt + 0.01:
            lines.append((current, False))
            current, used = [], 0.0
            word = dict(word, text=word["text"].lstrip())
            w = pool.width(word["entry"], word["text"], word["size"])
        current.append(word)
        used += w
    lines.append((current, True))
    return [(_merge_adjacent(items), last) for items, last in lines]


def _merge_adjacent(items):
    out = []
    for item in items:
        if out and all(out[-1][k] == item[k] for k in
                       ("entry", "size", "color", "underline", "strike")):
            out[-1] = dict(out[-1], text=out[-1]["text"] + item["text"])
        else:
            out.append(dict(item))
    return out


def line_metrics(pieces, pool, base_size):
    if not pieces:
        return base_size * 1.2, base_size * 0.9
    height = max(pool.line_height(p["entry"]) * p["size"] for p in pieces)
    ascent = max(pool.ascent(p["entry"]) * p["size"] for p in pieces)
    return height, ascent


def cell_line_heights(obj, pool, inner_w_pt):
    """Высоты готовых строк ячейки в пунктах."""
    lines = cell_lines(obj, pool, inner_w_pt)
    if obj.get("line_height"):
        return [obj["line_height"] * UNIT_TO_PT] * len(lines)
    return [line_metrics(p, pool, obj["font"]["size"])[0] for p, _ in lines]


def measure_cell(obj, pool, width_units):
    """Высота содержимого ячейки в units."""
    pad = obj.get("pad") or (2, 1, 2, 1)
    inner = max((width_units - pad[0] - pad[2]) * UNIT_TO_PT, 1.0)
    if obj.get("image"):
        return (obj.get("image_h") or obj["h"]) + pad[1] + pad[3]
    total = 0.0
    for pieces, _ in cell_lines(obj, pool, inner):
        height, _ = line_metrics(pieces, pool, obj["font"]["size"])
        total += height
    if obj.get("line_height"):
        total = len(cell_lines(obj, pool, inner)) * obj["line_height"] * UNIT_TO_PT
    return total / UNIT_TO_PT + pad[1] + pad[3]


def draw_cell(canvas, obj, x, y, w, h, pool, images, warnings, start=0,
              clip=False):
    """x, y — левый верхний угол в пунктах, w/h — размеры в пунктах.

    start — с какой строки текста рисовать (ячейка, разорванная страницей).
    Возвращает индекс первой ненарисованной строки или None, если всё вошло."""
    if obj.get("fill") and obj["fill"] != "FFFFFF":
        canvas.rect_fill(x, y, w, h, obj["fill"])

    pad = obj.get("pad") or (2, 1, 2, 1)
    pl, pt, pr, pb = [v * UNIT_TO_PT for v in pad]
    inner_w = max(w - pl - pr, 1.0)

    rest = None
    if obj.get("image"):
        _draw_image(canvas, obj, x + pl, y + pt, inner_w,
                    max(h - pt - pb, 1.0), images, warnings)
    else:
        rest = _draw_text(canvas, obj, x + pl, y + pt, inner_w,
                          max(h - pt - pb, 1.0), pool, start, clip)

    _draw_borders(canvas, obj, x, y, w, h, top=start == 0, bottom=rest is None)
    return rest


def _draw_borders(canvas, obj, x, y, w, h, top=True, bottom=True):
    brd = obj.get("brd") or {}
    if not any(brd.values()):
        return
    widths = obj.get("brd_w")
    style = obj.get("brd_style", "Solid")
    color = obj.get("brd_color", "000000")

    def width_of(side):
        if isinstance(widths, dict):
            return (widths.get(side) or 1.0) * UNIT_TO_PT
        return (widths or 1.0) * UNIT_TO_PT

    if brd.get("t") and top:
        canvas.line(x, y, x + w, y, width_of("t"), color, style)
    if brd.get("b") and bottom:
        canvas.line(x, y + h, x + w, y + h, width_of("b"), color, style)
    if brd.get("l"):
        canvas.line(x, y, x, y + h, width_of("l"), color, style)
    if brd.get("r"):
        canvas.line(x + w, y, x + w, y + h, width_of("r"), color, style)


def _draw_rotated(canvas, obj, x, y, w, h, pool):
    """Поворот на 90/270: строки идут вдоль высоты рамки."""
    angle = obj["angle"]
    lines = cell_lines(obj, pool, h)
    base_size = obj["font"]["size"]
    offset = 0.0
    for pieces, _last in lines:
        height, ascent = line_metrics(pieces, pool, base_size)
        length = sum(pool.width(p["entry"], p["text"], p["size"])
                     for p in pieces)
        along = {"Center": max((h - length) / 2.0, 0.0),
                 "Right": max(h - length, 0.0)}.get(obj.get("align"), 0.0)
        for piece in pieces:
            if angle == 90:
                px, py = x + offset + ascent, y + h - along
            else:
                px, py = x + w - offset - ascent, y + along
            canvas.text(px, py, piece["entry"], piece["size"], piece["text"],
                        piece["color"], angle)
            along += pool.width(piece["entry"], piece["text"], piece["size"])
        offset += height
    return None


def _draw_text(canvas, obj, x, y, w, h, pool, start=0, clip=False):
    if obj.get("angle") in (90, 270):
        return _draw_rotated(canvas, obj, x, y, w, h, pool)
    lines = cell_lines(obj, pool, w)
    if not lines:
        return None
    base_size = obj["font"]["size"]
    heights = [line_metrics(p, pool, base_size)[0] for p, _ in lines]
    if obj.get("line_height"):
        heights = [obj["line_height"] * UNIT_TO_PT] * len(lines)
    total = sum(heights[start:])

    offset = 0.0
    if obj.get("valign") == "Center":
        offset = max((h - total) / 2.0, 0.0)
    elif obj.get("valign") == "Bottom":
        offset = max(h - total, 0.0)

    align = ALIGN_CODE.get(obj.get("align", "Left"), ALIGN_LEFT)
    angle = obj.get("angle", 0)
    indent = (obj.get("indent") or 0.0) * UNIT_TO_PT

    cursor = y + offset
    for index, (pieces, last) in enumerate(lines):
        if index < start:
            continue
        height = heights[index]
        if clip and cursor + height > y + h + 0.5 and index > start:
            return index
        _, ascent = line_metrics(pieces, pool, base_size)
        baseline = cursor + ascent
        cursor += height
        if not pieces:
            continue
        first = index == 0 or (index and lines[index - 1][1])
        start_indent = indent if first else 0.0
        width = sum(pool.width(p["entry"], p["text"], p["size"])
                    for p in pieces)
        avail = w - start_indent
        if align == ALIGN_CENTER:
            px = x + start_indent + max((avail - width) / 2.0, 0.0)
        elif align == ALIGN_RIGHT:
            px = x + start_indent + max(avail - width, 0.0)
        else:
            px = x + start_indent

        if align == ALIGN_JUSTIFY and not last and width < avail:
            _draw_justified(canvas, pieces, px, baseline, avail, pool, angle)
            continue
        for piece in pieces:
            _draw_piece(canvas, piece, px, baseline, pool, angle)
            px += pool.width(piece["entry"], piece["text"], piece["size"])


def _draw_piece(canvas, piece, x, baseline, pool, angle):
    canvas.text(x, baseline, piece["entry"], piece["size"], piece["text"],
                piece["color"], angle)
    width = pool.width(piece["entry"], piece["text"], piece["size"])
    if piece.get("underline"):
        canvas.line(x, baseline + piece["size"] * 0.12,
                    x + width, baseline + piece["size"] * 0.12,
                    max(piece["size"] * 0.05, 0.4), piece["color"])
    if piece.get("strike"):
        canvas.line(x, baseline - piece["size"] * 0.28,
                    x + width, baseline - piece["size"] * 0.28,
                    max(piece["size"] * 0.05, 0.4), piece["color"])


def _draw_justified(canvas, pieces, x, baseline, avail, pool, angle):
    """Выключка по формату: слова расставляем сами — Tw при Identity-H
    не работает."""
    # ведущие пробелы — это отступ абзаца, он не участвует в разгонке
    lead = ""
    rest = list(pieces)
    while rest and not rest[0]["text"].strip():
        lead += rest[0]["text"]
        rest = rest[1:]
    if rest:
        head = rest[0]["text"]
        stripped = head.lstrip(" ")
        lead += head[:len(head) - len(stripped)]
        rest = [dict(rest[0], text=stripped)] + rest[1:]
    if lead:
        shift = pool.width(pieces[0]["entry"], lead, pieces[0]["size"])
        x += shift
        avail -= shift

    words = []
    for piece in rest:
        for token in piece["text"].split(" "):
            words.append(dict(piece, text=token))
    words = [w for w in words if w["text"] != ""]
    pieces = rest
    if len(words) < 2:
        for piece in pieces:
            _draw_piece(canvas, piece, x, baseline, pool, angle)
            x += pool.width(piece["entry"], piece["text"], piece["size"])
        return
    total = sum(pool.width(w["entry"], w["text"], w["size"]) for w in words)
    gap = (avail - total) / (len(words) - 1)
    for word in words:
        _draw_piece(canvas, word, x, baseline, pool, angle)
        x += pool.width(word["entry"], word["text"], word["size"]) + gap


def _draw_image(canvas, obj, x, y, w, h, images, warnings):
    key = obj["image"]
    name = images.get(key)
    if name is None:
        try:
            blob = base64.b64decode(key, validate=False)
        except Exception as exc:                               # noqa: BLE001
            warnings.append("картинка %s не декодируется: %s"
                            % (obj.get("name"), exc))
            images[key] = False
            return
        info = pdfimage.describe(blob)
        if not info:
            warnings.append("формат картинки %s не поддерживается встроенным "
                            "движком PDF" % obj.get("name"))
            images[key] = False
            return
        name = "Im%d" % (len([v for v in images.values() if v]) + 1)
        images[key] = name
        images.setdefault("__data__", {})[name] = info
    if name is False:
        return
    iw = (obj.get("image_w") or obj["w"]) * UNIT_TO_PT
    ih = (obj.get("image_h") or obj["h"]) * UNIT_TO_PT
    iw, ih = min(iw, w), min(ih, h)
    dx = {"Center": (w - iw) / 2.0, "Right": w - iw}.get(obj.get("align"), 0.0)
    dy = {"Center": (h - ih) / 2.0, "Bottom": h - ih}.get(obj.get("valign"), 0.0)
    canvas.image(name, x + max(dx, 0.0), y + max(dy, 0.0), iw, ih)


# --------------------------------------------------------------------------
# страницы
# --------------------------------------------------------------------------
def _row_heights(block, pool):
    """Высоты строк с учётом того, что текст может не поместиться."""
    heights = list(block["row_heights"])
    for ri, ci, rs, cs, obj in block["spans"]:
        width = sum(block["cols"][ci:ci + cs])
        need = measure_cell(obj, pool, width)
        have = sum(heights[ri:ri + rs])
        if need > have + 0.5:
            heights[min(ri + rs - 1, len(heights) - 1)] += need - have
    return heights


def _breakable(block, index):
    """Можно ли начать новую страницу перед строкой index."""
    for ri, _ci, rs, _cs, _obj in block["spans"]:
        if ri < index < ri + rs:
            return False
    return True


class PageBuilder(object):
    """Поток блоков с разбиением на страницы."""

    def __init__(self, page, pool, images, warnings, first_number=1):
        self.page = page
        self.first_number = first_number
        self.pool = pool
        self.images = images
        self.warnings = warnings
        self.canvases = []
        self.width = page["width"] * DXA_TO_PT
        self.height = page["height"] * DXA_TO_PT
        self.left = page["margins"]["left"] * DXA_TO_PT
        self.right = page["margins"]["right"] * DXA_TO_PT
        self.top = page["margins"]["top"] * DXA_TO_PT
        self.bottom = page["margins"]["bottom"] * DXA_TO_PT
        self.header, _ = part_blocks(page["header"], page["body_units"],
                                     warnings)
        self.footer, _ = part_blocks(page["footer"], page["body_units"],
                                     warnings)
        self.header_h = self._part_height(self.header)
        self.footer_h = self._part_height(self.footer)
        self.body_top = self.top + self.header_h
        self.body_bottom = self.height - self.bottom - self.footer_h
        self.canvas = None
        self.y = 0.0
        self._warned_overflow = False
        self._new_page()

    def _part_height(self, blocks):
        total = 0.0
        for block in blocks:
            if block["type"] == "spacer":
                total += block["h"] * UNIT_TO_PT
            else:
                total += sum(_row_heights(block, self.pool)) * UNIT_TO_PT
        return total

    def _new_page(self):
        self.canvas = Canvas(self.width, self.height, self.pool, self.images)
        self.canvases.append(self.canvas)
        PAGE_CONTEXT["page"] = self.first_number + len(self.canvases) - 1
        self.y = self.body_top
        self._draw_part(self.header, self.top)
        self._draw_part(self.footer, self.height - self.bottom - self.footer_h)
        if self.page.get("watermark"):
            self._draw_watermark()

    def _draw_part(self, blocks, start_y):
        y = start_y
        for block in blocks:
            if block["type"] == "spacer":
                y += block["h"] * UNIT_TO_PT
                continue
            y = self._draw_table(self.canvas, block, y,
                                 _row_heights(block, self.pool))

    def _draw_watermark(self):
        entry = self.pool.use(self.page.get("watermark_font", {}).get("name",
                                                                     "Arial"))
        text = self.page["watermark"]
        size = 60.0
        width = self.pool.width(entry, text, size)
        x = max((self.width - width) / 2.0, 0.0)
        self.canvas.text(x, self.height / 2.0, entry, size, text, "C0C0C0")

    def _draw_table(self, canvas, block, y, heights):
        cols = block["cols"]
        xs = [self.left]
        for w in cols:
            xs.append(xs[-1] + w * UNIT_TO_PT)
        tops = [y]
        for h in heights:
            tops.append(tops[-1] + h * UNIT_TO_PT)
        for ri, ci, rs, cs, obj in block["spans"]:
            x = xs[ci]
            w = xs[min(ci + cs, len(xs) - 1)] - x
            top = tops[ri]
            h = tops[min(ri + rs, len(tops) - 1)] - top
            draw_cell(canvas, obj, x, top, w, h, self.pool, self.images,
                      self.warnings)
        return tops[-1]

    def add_spacer(self, height_units):
        self.y += height_units * UNIT_TO_PT
        if self.y > self.body_bottom:
            self._new_page()

    def _column_x(self, block):
        xs = [self.left]
        for w in block["cols"]:
            xs.append(xs[-1] + w * UNIT_TO_PT)
        return xs

    def _split_row(self, block, index):
        """Строка выше страницы: льём её текст с переносом через разрывы."""
        xs = self._column_x(block)
        pending = []
        for ri, ci, rs, cs, obj in block["spans"]:
            if ri != index:
                continue
            pending.append([ci, cs, obj, 0])
        while pending:
            avail = self.body_bottom - self.y
            drawn = 0.0
            nxt = []
            for ci, cs, obj, start in pending:
                x = xs[ci]
                w = xs[min(ci + cs, len(xs) - 1)] - x
                rest = draw_cell(self.canvas, obj, x, self.y, w, avail,
                                 self.pool, self.images, self.warnings,
                                 start, clip=True)
                pad = obj.get("pad") or (2, 1, 2, 1)
                inner = max(w - (pad[0] + pad[2]) * UNIT_TO_PT, 1.0)
                lines = cell_line_heights(obj, self.pool, inner)
                stop = rest if rest is not None else len(lines)
                drawn = max(drawn, sum(lines[start:stop])
                            + (pad[1] + pad[3]) * UNIT_TO_PT)
                if rest is not None:
                    nxt.append([ci, cs, obj, rest])
            self.y += min(drawn, avail)
            if not nxt:
                return
            pending = nxt
            self._new_page()

    def add_table(self, block):
        heights = _row_heights(block, self.pool)
        body_height = self.body_bottom - self.body_top
        start = 0
        while start < len(heights):
            row_pt = heights[start] * UNIT_TO_PT
            # строка выше целой страницы — рвём её текст построчно
            if (row_pt > body_height and _breakable(block, start)
                    and _breakable(block, start + 1)):
                if self.y > self.body_top + 0.5:
                    self._new_page()
                self._split_row(block, start)
                start += 1
                continue
            # строка не влезает в остаток страницы — начинаем новую
            if self.y > self.body_top + 0.5 and self.y + row_pt > self.body_bottom:
                self._new_page()
            end, used = start, 0.0
            while end < len(heights):
                nxt = used + heights[end] * UNIT_TO_PT
                if self.y + nxt > self.body_bottom and end > start:
                    cut = end
                    while cut > start and not _breakable(block, cut):
                        cut -= 1
                    if cut > start:
                        end = cut
                        used = sum(heights[start:end]) * UNIT_TO_PT
                        break
                    # объединённые ячейки не дают разрыва — кладём как есть
                used = nxt
                end += 1
            piece = _slice_block(block, start, end)
            self._draw_table(self.canvas, piece, self.y, heights[start:end])
            self.y += used
            if self.y > self.body_bottom and not self._warned_overflow:
                self._warned_overflow = True
                self.warnings.append(
                    "блок выше страницы целиком (объединённые ячейки) — "
                    "во встроенном PDF он выходит за нижнее поле")
            start = end
            if start < len(heights):
                self._new_page()

    def flush(self):
        return self.canvases


def _slice_block(block, start, end):
    spans = []
    for ri, ci, rs, cs, obj in block["spans"]:
        if start <= ri < end:
            spans.append((ri - start, ci, min(rs, end - ri), cs, obj))
    return {"type": "table", "cols": block["cols"],
            "row_heights": block["row_heights"][start:end], "spans": spans}


# --------------------------------------------------------------------------
# сборка файла
# --------------------------------------------------------------------------
def _render_all(pages, warnings, total):
    """Раскладка всех страниц. Прогон делается дважды: на первом становится
    известно общее число страниц для [TotalPages]."""
    pool = FontPool(warnings)
    images = {}
    rendered = []
    PAGE_CONTEXT["total"] = total
    for page in pages:
        builder = PageBuilder(page, pool, images, warnings,
                              first_number=len(rendered) + 1)
        blocks, _ = page_blocks(page, warnings)
        for block in blocks:
            if block["type"] == "spacer":
                builder.add_spacer(block["h"])
            else:
                builder.add_table(block)
        for canvas in builder.flush():
            rendered.append((canvas, builder.width, builder.height))
    return pool, images, rendered


def build_pdf(pages, path, warnings, title=None):
    quiet = []
    _pool, _images, first = _render_all(pages, quiet, 1)
    pool, images, rendered = _render_all(pages, warnings, len(first))

    pdf = Pdf()
    catalog = pdf.reserve()
    pages_obj = pdf.reserve()
    image_refs = _emit_images(pdf, images)
    font_dict = pool.emit(pdf)

    kids = []
    for canvas, width, height in rendered:
        content = pdf.add_stream("", canvas.content())
        used = {name: image_refs[name] for name in canvas.used_images
                if name in image_refs}
        xobj = ("/XObject << %s >>"
                % " ".join("/%s %d 0 R" % (n, r) for n, r in used.items())
                if used else "")
        kids.append(pdf.add(
            "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
            "/Resources << /Font %s %s >> /Contents %d 0 R >>"
            % (pages_obj, width, height, font_dict, xobj, content)))

    pdf.put(pages_obj, "<< /Type /Pages /Count %d /Kids [%s] >>"
            % (len(kids), " ".join("%d 0 R" % k for k in kids)))
    pdf.put(catalog, "<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    info = pdf.add("<< /Producer (frx2docx) /Creator (frx2docx)%s >>"
                   % (" /Title %s" % pdf_string(title) if title else ""))
    pdf.save(path, catalog, info)
    return path


def _emit_images(pdf, images):
    refs = {}
    for name, info in (images.get("__data__") or {}).items():
        space = {1: "/DeviceGray", 3: "/DeviceRGB",
                 4: "/DeviceCMYK"}.get(info["colors"], "/DeviceRGB")
        body = ("/Type /XObject /Subtype /Image /Width %d /Height %d "
                "/ColorSpace %s /BitsPerComponent %d /Filter %s /Length %d"
                % (info["width"], info["height"], space, info["bpc"],
                   info["filter"], len(info["data"])))
        refs[name] = pdf.add(b"<< " + body.encode("latin-1") + b" >>\nstream\n"
                             + info["data"] + b"\nendstream")
    return refs
