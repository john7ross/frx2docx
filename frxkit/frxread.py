# -*- coding: utf-8 -*-
"""Чтение .frx: XML FastReport -> модель абсолютных прямоугольников.

Модель намеренно плоская. Каждый видимый объект шаблона превращается в
прямоугольник с координатами в units (1/96 дюйма) и полным набором оформления.
Дальше с прямоугольниками работают layout.py (сетка) и писатели docx/pdf.
"""

from __future__ import annotations

import base64
import os
import re
import xml.etree.ElementTree as ET

from . import barcode
from .common import (CONTAINERS, PAPER_SIZES, MM_TO_DXA, UNIT_TO_DXA,
                     fnum, object_fill, parse_border, parse_color, parse_font,
                     parse_inline_html, parse_padding, strip_html)
from .rtf import rtf_to_lines, rtf_to_text

# бэнды, которые в Word становятся колонтитулами
HEADER_BANDS = ("PageHeaderBand",)
FOOTER_BANDS = ("PageFooterBand",)
# бэнды, которые в поток документа не идут
SKIP_BANDS = ("OverlayBand",)

NON_OBJECT_TAGS = ("Formats", "GeneralFormat", "NumberFormat", "DateFormat",
                   "CurrencyFormat", "PercentFormat", "BooleanFormat",
                   "CustomFormat", "Fill", "Padding", "Highlight", "Condition",
                   "Sort", "Style", "Border", "Font")

SERVICE_TAGS = ("ScriptText", "Dictionary", "Styles", "Fill", "Padding",
                "Formats", "Style", "Highlight")


# --------------------------------------------------------------------------
# чтение файла
# --------------------------------------------------------------------------
def read_frx(path):
    """Разбор .frx в любом объявленном шифровании (обычно utf-8 или cp1251)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    m = re.match(rb"\s*<\?xml[^>]*encoding=[\"']([\w\-]+)[\"']", raw)
    enc = m.group(1).decode("ascii") if m else "utf-8"
    try:
        text = raw.decode(enc if enc.lower() != "utf-8" else "utf-8-sig")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1).lstrip("﻿").lstrip()
    return ET.fromstring(text)


# --------------------------------------------------------------------------
# прямоугольник
# --------------------------------------------------------------------------
def html_enabled(el):
    return (el.attrib.get("HtmlTags", "").lower() == "true"
            or el.attrib.get("TextRenderType", "") in ("HtmlTags",
                                                       "HtmlParagraph"))


def border_widths(el, default=1.0):
    """Толщина рамки: общая Border.Width плюс возможные Border.<Side>Line.Width."""
    base = fnum(el, "Border.Width", default) or default
    widths = {"t": base, "r": base, "b": base, "l": base}
    for side, key in (("t", "Top"), ("r", "Right"), ("b", "Bottom"),
                      ("l", "Left")):
        w = fnum(el, "Border.%sLine.Width" % key, 0.0)
        if w > 0:
            widths[side] = w
    return widths


def text_color(el):
    return (parse_color(el.attrib.get("TextColor"))
            or parse_color(el.attrib.get("TextFill.Color")))


def make_rect(el, x, y, w, h, text, warnings, kind="text"):
    html_on = html_enabled(el)
    pad = parse_padding(el.attrib.get("Padding"))
    rect = {
        "kind": kind,
        "name": el.attrib.get("Name", ""),
        "x": round(x, 2), "y": round(y, 2),
        "w": round(w, 2), "h": round(h, 2),
        "text": strip_html(text or "", html_on),
        "font": parse_font(el.attrib.get("Font")),
        "color": text_color(el),
        "fill": object_fill(el),
        "align": el.attrib.get("HorzAlign", "Left"),
        "valign": el.attrib.get("VertAlign", "Top"),
        "brd": parse_border(el.attrib.get("Border.Lines")),
        "brd_w": border_widths(el),
        "brd_style": el.attrib.get("Border.Style", "Solid"),
        "brd_color": parse_color(el.attrib.get("Border.Color")) or "000000",
        "pad": pad,
        "indent": fnum(el, "ParagraphOffset", 0.0),
        "line_height": fnum(el, "LineHeight", 0.0) or None,
        "angle": int(fnum(el, "Angle", 0.0)) % 360,
        "wrap": el.attrib.get("WordWrap", "true").lower() != "false",
        "url": el.attrib.get("Hyperlink.Value") or None,
        "image": None,
        "runs": None,
    }
    if html_on and text and "<" in text:
        rect["runs"] = parse_inline_html(text)
    if rect["angle"] not in (0, 90, 180, 270):
        warnings.append("поворот текста %s на %d° не поддерживается Word — "
                        "текст поставлен горизонтально"
                        % (rect["name"], rect["angle"]))
        rect["angle"] = 0
    return rect


# --------------------------------------------------------------------------
# отдельные типы объектов
# --------------------------------------------------------------------------
def barcode_rect(el, x, y, warnings):
    """BarcodeObject. Константное содержимое рисуется настоящим штрихкодом;
    если содержимое — выражение ([root.Field]), данных на этапе шаблона нет:
    ставим рамку исходного размера с подписью, откуда берутся данные."""
    kind = el.attrib.get("Barcode", "Barcode")
    data = (el.attrib.get("Text") or "").strip()
    w, h = fnum(el, "Width"), fnum(el, "Height")
    is_expression = "[" in data
    rect = make_rect(el, x, y, w, h, "", warnings, kind="barcode")
    rect["align"] = "Center"
    rect["valign"] = "Center"

    if not is_expression and data:
        png, info = barcode.render(
            kind, data, height=max(int(h * 2), 40))
        if png:
            square = info is True
            side = min(w, h) if square else None
            rect["image"] = base64.b64encode(png).decode()
            rect["image_w"] = side if square else w
            rect["image_h"] = side if square else h
            return rect
        warnings.append("штрихкод %s (%s): %s — вставлена рамка-заглушка"
                        % (el.attrib.get("Name"), kind, info))

    rect["text"] = "%s\r\n%s" % (kind, data or "(без данных)")
    if is_expression:
        warnings.append("%s %s: содержимое задано выражением %s, картинка "
                        "штрихкода не строится — вставлена рамка исходного "
                        "размера с подписью"
                        % (kind, el.attrib.get("Name"), data))
    return rect


def picture_rect(el, x, y, warnings, base_dir=None):
    """PictureObject: base64 в атрибуте Image либо файл в ImageLocation."""
    w, h = fnum(el, "Width"), fnum(el, "Height")
    rect = make_rect(el, x, y, w, h, "", warnings, kind="picture")
    data = el.attrib.get("Image")
    if not data:
        child = el.find("Image")
        if child is not None and (child.text or "").strip():
            data = child.text.strip()
    if not data:
        location = el.attrib.get("ImageLocation") or ""
        if location and "[" not in location:
            path = location
            if base_dir and not os.path.isabs(path):
                path = os.path.join(base_dir, path)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    data = base64.b64encode(fh.read()).decode()
            else:
                warnings.append("PictureObject %s ссылается на %s — файл не "
                                "найден" % (el.attrib.get("Name"), location))
    if not data:
        return None
    rect["image"] = data
    mode = el.attrib.get("SizeMode", "Zoom")
    rect["image_mode"] = mode
    if mode in ("Normal", "Center"):
        rect["image_w"], rect["image_h"] = _image_size(data, w, h)
    else:
        rect["image_w"], rect["image_h"] = w, h
    return rect


def _image_size(b64, max_w, max_h):
    """Натуральный размер картинки в units (96 dpi), обрезанный по рамке."""
    try:
        blob = base64.b64decode(b64, validate=False)
    except Exception:                                          # noqa: BLE001
        return max_w, max_h
    size = _png_size(blob) or _jpeg_size(blob)
    if not size:
        return max_w, max_h
    w, h = size
    if w <= 0 or h <= 0:
        return max_w, max_h
    scale = min(max_w / w, max_h / h, 1.0)
    return w * scale, h * scale


def _png_size(blob):
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    import struct
    return struct.unpack(">II", blob[16:24])


def _jpeg_size(blob):
    if blob[:2] != b"\xff\xd8":
        return None
    import struct
    i = 2
    while i + 9 < len(blob):
        if blob[i] != 0xFF:
            i += 1
            continue
        marker = blob[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", blob[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", blob[i + 5:i + 9])
            return w, h
        i += 2 + length
    return None


def line_rect(el, x, y, warnings):
    """LineObject: горизонтальная или вертикальная линия -> ячейка с одной
    границей. Диагональ в табличную сетку не ложится."""
    w, h = fnum(el, "Width"), fnum(el, "Height")
    if abs(w) > 1.0 and abs(h) > 1.0:
        warnings.append("LineObject %s — диагональная линия, пропущена"
                        % el.attrib.get("Name"))
        return None
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    rect = make_rect(el, x, y, max(w, 1.0), max(h, 1.0), "", warnings,
                     kind="line")
    side = "t" if w >= h else "l"
    rect["brd"] = {"t": 0, "r": 0, "b": 0, "l": 0}
    rect["brd"][side] = 1
    width = fnum(el, "Border.Width", 1.0) or 1.0
    rect["brd_w"] = {"t": width, "r": width, "b": width, "l": width}
    rect["brd_style"] = el.attrib.get("Border.Style", "Solid")
    rect["brd_color"] = parse_color(el.attrib.get("Border.Color")) or "000000"
    rect["fill"] = None
    return rect


ROUND_SHAPES = ("Ellipse", "RoundRectangle", "Triangle", "Diamond")


def shape_rect(el, x, y, warnings, seen):
    """ShapeObject: прямоугольник переносится точно, остальные фигуры
    приближаются прямоугольником."""
    shape = el.attrib.get("Shape", "Rectangle")
    rect = make_rect(el, x, y, fnum(el, "Width"), fnum(el, "Height"), "",
                     warnings, kind="shape")
    rect["brd"] = {"t": 1, "r": 1, "b": 1, "l": 1}
    width = fnum(el, "Border.Width", 1.0) or 1.0
    rect["brd_w"] = {"t": width, "r": width, "b": width, "l": width}
    if shape in ROUND_SHAPES and shape not in seen:
        seen.add(shape)
        warnings.append("ShapeObject %s: фигура %s заменена прямоугольником"
                        % (el.attrib.get("Name"), shape))
    return rect


def checkbox_rect(el, x, y, warnings):
    checked = el.attrib.get("Checked", "true").lower() != "false"
    rect = make_rect(el, x, y, fnum(el, "Width"), fnum(el, "Height"),
                     "☒" if checked else "☐", warnings,
                     kind="checkbox")
    rect["align"] = el.attrib.get("HorzAlign", "Center")
    rect["valign"] = el.attrib.get("VertAlign", "Center")
    if el.attrib.get("Expression"):
        warnings.append("CheckBoxObject %s управляется выражением %s — "
                        "в docx показано состояние из шаблона"
                        % (el.attrib.get("Name"), el.attrib["Expression"]))
    return rect


def rich_rect(el, x, y, warnings):
    raw = el.attrib.get("Text", "")
    if not raw:
        child = el.find("Text")
        if child is not None:
            raw = child.text or ""
    lines, align = rtf_to_lines(raw)
    rect = make_rect(el, x, y, fnum(el, "Width"), fnum(el, "Height"),
                     rtf_to_text(raw), warnings, kind="rich")
    rect["runs"] = lines
    if align and "HorzAlign" not in el.attrib:
        rect["align"] = align
    sizes = [f["size"] for ln in lines for f in ln if f.get("size")]
    if sizes:
        rect["font"] = dict(rect["font"], size=min(sizes))
    faces = [f["face"] for ln in lines for f in ln if f.get("face")]
    if faces:
        rect["font"] = dict(rect["font"], name=faces[0])
    return rect


# --------------------------------------------------------------------------
# таблицы
# --------------------------------------------------------------------------
def flatten_table(tbl, ox, oy, out, warnings, base_dir=None):
    tox, toy = ox + fnum(tbl, "Left"), oy + fnum(tbl, "Top")
    cols = [fnum(c, "Width") for c in tbl if c.tag == "TableColumn"]
    rows = [r for r in tbl if r.tag == "TableRow"]
    if not cols or not rows:
        return
    ncols = len(cols)
    total_w = fnum(tbl, "Width")
    blank_cols = [i for i, v in enumerate(cols) if v <= 0]
    if blank_cols:
        rest = total_w - sum(v for v in cols if v > 0)
        share = rest / len(blank_cols) if rest > 0 else 0.0
        for i in blank_cols:
            cols[i] = share
        if share <= 0:
            warnings.append("в таблице %s у колонки нет ширины и её нечем "
                            "восполнить" % tbl.attrib.get("Name", "?"))
    total_h = fnum(tbl, "Height")
    heights = [fnum(r, "Height", 0.0) for r in rows]
    unset = [i for i, v in enumerate(heights) if v <= 0]
    if unset:
        rest = total_h - sum(h for h in heights if h > 0)
        share = rest / len(unset) if rest > 0 else 18.9
        for i in unset:
            heights[i] = share
    tbl_border = parse_border(tbl.attrib.get("Border.Lines"))

    x_at = [sum(cols[:i]) for i in range(ncols + 1)]
    y_at = [sum(heights[:i]) for i in range(len(rows) + 1)]
    occupied = set()

    for ri, row in enumerate(rows):
        cells = [c for c in row if c.tag == "TableCell"]
        # FastReport обычно сериализует ячейку под каждую колонку; если их
        # меньше — значит перекрытые ячейки опущены, тогда двигаем указатель.
        dense = len(cells) >= ncols
        col = 0
        for idx, cell in enumerate(cells):
            if dense:
                col = idx
                if (ri, col) in occupied:
                    continue
            else:
                while col < ncols and (ri, col) in occupied:
                    col += 1
            if col >= ncols:
                break
            cspan = max(1, int(fnum(cell, "ColSpan", 1) or 1))
            rspan = max(1, int(fnum(cell, "RowSpan", 1) or 1))
            cspan = min(cspan, ncols - col)
            rspan = min(rspan, len(rows) - ri)
            w = x_at[col + cspan] - x_at[col]
            h = y_at[ri + rspan] - y_at[ri]
            rect = make_rect(cell, tox + x_at[col], toy + y_at[ri], w, h,
                             cell.attrib.get("Text"), warnings, kind="cell")
            if "Border.Lines" not in cell.attrib:
                rect["brd"] = dict(tbl_border)
            nested = nested_fragments(cell, warnings, base_dir)
            if nested["text"]:
                parts = ([rect["text"]] if rect["text"].strip() else []) \
                    + nested["text"]
                rect["text"] = "\r\n".join(parts)
            if nested["image"] and not rect["image"]:
                rect["image"] = nested["image"]["image"]
                rect["image_w"] = nested["image"].get("image_w")
                rect["image_h"] = nested["image"].get("image_h")
            out.append(rect)
            for rr in range(ri, ri + rspan):
                for cc in range(col, col + cspan):
                    occupied.add((rr, cc))
            if not dense:
                col += cspan


def nested_fragments(cell, warnings, base_dir=None):
    """Объекты, вложенные в ячейку таблицы (галки, подписи, картинки).
    Отдельными прямоугольниками их не разложить — сводим в текст ячейки
    в порядке сверху вниз; картинку кладём в саму ячейку."""
    kids = []
    for child in cell:
        if child.tag in NON_OBJECT_TAGS:
            continue
        if child.attrib.get("Visible", "").lower() == "false":
            continue
        kids.append(child)
    result = {"text": [], "image": None}
    if not kids:
        return result
    kids.sort(key=lambda e: (fnum(e, "Top"), fnum(e, "Left")))

    for e in kids:
        if e.tag == "CheckBoxObject":
            checked = e.attrib.get("Checked", "true").lower() != "false"
            result["text"].append("☒" if checked else "☐")
            if e.attrib.get("Expression"):
                warnings.append("CheckBoxObject %s управляется выражением %s — "
                                "в docx показано состояние из шаблона"
                                % (e.attrib.get("Name"), e.attrib["Expression"]))
        elif e.tag == "TextObject":
            result["text"].append(strip_html(e.attrib.get("Text", ""),
                                             html_enabled(e)))
        elif e.tag == "RichObject":
            result["text"].append(rtf_to_text(e.attrib.get("Text", "")))
        elif e.tag == "PictureObject":
            pic = picture_rect(e, 0, 0, warnings, base_dir)
            if pic and pic.get("image"):
                result["image"] = pic
            else:
                warnings.append("PictureObject %s внутри ячейки %s пуст "
                                "(картинка подставляется скриптом)"
                                % (e.attrib.get("Name"),
                                   cell.attrib.get("Name")))
        elif e.tag == "BarcodeObject":
            bc = barcode_rect(e, 0, 0, warnings)
            if bc.get("image"):
                result["image"] = bc
            else:
                result["text"].append(bc["text"])
        else:
            warnings.append("объект %s внутри ячейки пропущен" % e.tag)
    result["text"] = [x for x in result["text"] if x != ""]
    return result


# --------------------------------------------------------------------------
# развёртка бэнда
# --------------------------------------------------------------------------
def flatten(container, ox, oy, out, warnings, seen, base_dir=None):
    for el in container:
        tag = el.tag
        if el.attrib.get("Visible", "").lower() == "false":
            continue
        x, y = ox + fnum(el, "Left"), oy + fnum(el, "Top")
        if tag == "TextObject":
            out.append(make_rect(el, x, y, fnum(el, "Width"),
                                 fnum(el, "Height"), el.attrib.get("Text"),
                                 warnings))
        elif tag == "RichObject":
            out.append(rich_rect(el, x, y, warnings))
        elif tag == "BarcodeObject":
            out.append(barcode_rect(el, x, y, warnings))
        elif tag == "CheckBoxObject":
            out.append(checkbox_rect(el, x, y, warnings))
        elif tag == "PictureObject":
            rect = picture_rect(el, x, y, warnings, base_dir)
            if rect is not None:
                out.append(rect)
            elif "PictureObject" not in seen:
                seen.add("PictureObject")
                warnings.append("PictureObject без встроенного изображения "
                                "пропущен")
        elif tag == "LineObject":
            rect = line_rect(el, x, y, warnings)
            if rect is not None:
                out.append(rect)
        elif tag in ("ShapeObject", "PolygonObject", "PolyLineObject"):
            out.append(shape_rect(el, x, y, warnings, seen))
        elif tag == "TableObject":
            flatten_table(el, ox, oy, out, warnings, base_dir)
        elif tag == "ZipCodeObject":
            rect = make_rect(el, x, y, fnum(el, "Width"), fnum(el, "Height"),
                             el.attrib.get("Text", ""), warnings)
            out.append(rect)
        elif tag.endswith(CONTAINERS):
            continue          # вложенные бэнды обрабатываются отдельно
        elif tag in SERVICE_TAGS:
            continue
        elif tag in ("SubreportObject",):
            page = el.attrib.get("ReportPage")
            warnings.append("SubreportObject %s ссылается на страницу %s — "
                            "она перенесена отдельной секцией"
                            % (el.attrib.get("Name"), page))
        else:
            if tag not in seen:
                seen.add(tag)
                warnings.append("объект %s не поддерживается и пропущен" % tag)


def band_objects(band, warnings, seen, base_dir=None):
    """Плоский список прямоугольников бэнда вместе с вложенными бэндами."""
    bands = []

    def walk(node, offset):
        objs = []
        flatten(node, 0.0, 0.0, objs, warnings, seen, base_dir)
        objs = [o for o in objs if o["w"] > 0.5 and o["h"] > 0.5]
        if objs:
            bands.append({"name": node.attrib.get("Name", node.tag),
                          "top": offset, "objs": objs})
        for child in node:
            if child.tag.endswith("Band"):
                walk(child, fnum(child, "Top"))

    walk(band, fnum(band, "Top"))
    return bands


def collect_page(page, warnings, seen, base_dir=None):
    """ReportPage -> {'body': [бэнды], 'header': [объекты], 'footer': [...]}"""
    body, header, footer = [], [], []
    for child in page:
        if not child.tag.endswith("Band"):
            continue
        if child.attrib.get("Visible", "").lower() == "false":
            continue
        if child.tag in SKIP_BANDS:
            warnings.append("%s %s пропущен: в Word ему нет соответствия"
                            % (child.tag, child.attrib.get("Name")))
            continue
        chunks = band_objects(child, warnings, seen, base_dir)
        if child.tag in HEADER_BANDS:
            header.extend(chunks)
        elif child.tag in FOOTER_BANDS:
            footer.extend(chunks)
        else:
            body.extend(chunks)
    body.sort(key=lambda b: b["top"])
    return {"body": body, "header": header, "footer": footer}


# для обратной совместимости со старым verify_layout.py
def collect_bands(page, warnings, seen):
    parts = collect_page(page, warnings, seen)
    return parts["body"] + parts["header"] + parts["footer"]


# --------------------------------------------------------------------------
# геометрия страницы
# --------------------------------------------------------------------------
def page_geometry(page, warnings):
    """(ширина, высота, поля) в dxa + рабочая ширина в units."""
    pw_mm = fnum(page, "PaperWidth", 0.0)
    ph_mm = fnum(page, "PaperHeight", 0.0)
    if pw_mm <= 0 or ph_mm <= 0:
        raw = int(fnum(page, "RawPaperSize", 9))
        if raw not in PAPER_SIZES:
            warnings.append("неизвестный RawPaperSize=%s, взят A4" % raw)
        pw_mm, ph_mm = PAPER_SIZES.get(raw, (210.0, 297.0))
    if page.attrib.get("Landscape", "").lower() == "true":
        pw_mm, ph_mm = ph_mm, pw_mm
    margins_mm = {
        "left": fnum(page, "LeftMargin", 10.0),
        "right": fnum(page, "RightMargin", 10.0),
        "top": fnum(page, "TopMargin", 10.0),
        "bottom": fnum(page, "BottomMargin", 10.0),
    }
    width_dxa = int(round(pw_mm * MM_TO_DXA))
    height_dxa = int(round(ph_mm * MM_TO_DXA))
    m_dxa = {k: int(round(v * MM_TO_DXA)) for k, v in margins_mm.items()}
    body_units = (width_dxa - m_dxa["left"] - m_dxa["right"]) / UNIT_TO_DXA
    return width_dxa, height_dxa, m_dxa, body_units


def report_pages(root, warnings, include_hidden=False):
    """Видимые страницы отчёта. Скрытые FastReport при печати не выводит."""
    pages, hidden = [], []
    for p in root:
        if p.tag != "ReportPage":
            continue
        if not include_hidden and p.attrib.get("Visible", "").lower() == "false":
            hidden.append(p.attrib.get("Name", "?"))
            continue
        pages.append(p)
    if hidden:
        warnings.append("страницы %s помечены Visible=false и пропущены "
                        "(ключ --all-pages переносит и их)"
                        % ", ".join(hidden))
    return pages


def page_info(page, warnings, seen, base_dir=None):
    """Полное описание страницы для писателей docx/pdf."""
    width, height, margins, body_units = page_geometry(page, warnings)
    parts = collect_page(page, warnings, seen, base_dir)
    columns = int(fnum(page, "Columns.Count", 1) or 1)
    if columns > 1:
        warnings.append("страница %s свёрстана в %d колонки"
                        % (page.attrib.get("Name"), columns))
    watermark = page.attrib.get("Watermark.Text") or None
    if watermark and page.attrib.get("Watermark.Enabled", "true").lower() == "false":
        watermark = None
    return {
        "name": page.attrib.get("Name", ""),
        "width": width, "height": height, "margins": margins,
        "body_units": body_units, "columns": columns,
        "watermark": watermark,
        "watermark_font": parse_font(page.attrib.get("Watermark.Font")),
        "body": parts["body"], "header": parts["header"],
        "footer": parts["footer"],
    }
