# -*- coding: utf-8 -*-
"""Модель документа -> шаблон FastReport (.frx).

FastReport размещает объекты по абсолютным координатам, поэтому писатель
сам считает высоту каждого абзаца по метрикам шрифта (frxkit.fonts) и
складывает объекты сверху вниз. Получается шаблон, который открывается
в дизайнере и печатается так же, как исходный документ.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from . import fonts
from .common import (MM_TO_UNIT, PT_TO_UNIT, format_border, format_color,
                     format_font, runs_to_html)
from .doctree import DEFAULT_FONT, DEFAULT_SIZE, plain_text, runs_differ, \
    uniform_font

CREATOR = "frx2docx"
CELL_PAD = 4.0                 # отступы внутри ячейки, units (2 слева+справа)
LINE_FACTOR = 1.18             # межстрочный интервал по умолчанию


def _num(value):
    return ("%g" % round(float(value), 2))


def measure_runs(runs, width_units, base=None, indent=0.0):
    """Высота абзаца в units при заданной ширине."""
    base = base or uniform_font(runs)
    text = plain_text(runs)
    width_pt = max((width_units - CELL_PAD) / PT_TO_UNIT, 1.0)
    size = base["size"] or DEFAULT_SIZE
    total = 0
    for chunk in text.split("\n"):
        first_width = width_pt - indent / PT_TO_UNIT
        lines = fonts.wrap(chunk, base["name"], size, max(first_width, 1.0),
                           base["bold"], base["italic"])
        total += max(len(lines), 1)
    return total * size * LINE_FACTOR * PT_TO_UNIT


def _set_font(el, base):
    el.set("Font", format_font(base))


def _set_borders(el, borders, color="000000", width=1.0):
    value = format_border(borders)
    if value:
        el.set("Border.Lines", value)
        if color and color != "000000":
            el.set("Border.Color", format_color(color))
        if width and abs(width - 1.0) > 0.01:
            el.set("Border.Width", _num(width))


def _set_text(el, runs, base):
    """Текст объекта: простой или с разметкой, если оформление неоднородно."""
    if runs_differ(runs, base):
        el.set("TextRenderType", "HtmlTags")
        el.set("Text", runs_to_html([runs]))
    else:
        el.set("Text", plain_text(runs).replace("\n", "\r\n"))
    color = next((r.get("color") for r in runs if r.get("color")), None)
    if color and not runs_differ(runs, base):
        el.set("TextColor", format_color(color))


class Builder(object):
    def __init__(self, warnings):
        self.warnings = warnings
        self.counter = {}

    def name(self, prefix):
        self.counter[prefix] = self.counter.get(prefix, 0) + 1
        return "%s%d" % (prefix, self.counter[prefix])

    # -- блоки -------------------------------------------------------------
    def paragraph(self, parent, block, y, width):
        base = uniform_font(block["runs"])
        indent = block.get("indent") or 0.0
        height = measure_runs(block["runs"], width, base, indent)
        el = ET.SubElement(parent, "TextObject")
        el.set("Name", self.name("Text"))
        el.set("Left", "0")
        el.set("Top", _num(y))
        el.set("Width", _num(width))
        el.set("Height", _num(height))
        el.set("CanGrow", "true")
        if block.get("align", "Left") != "Left":
            el.set("HorzAlign", block["align"])
        if indent:
            el.set("ParagraphOffset", _num(indent))
        if block.get("line_height"):
            el.set("LineHeight", _num(block["line_height"]))
        _set_font(el, base)
        _set_text(el, block["runs"], base)
        return height

    def image(self, parent, block, y, width):
        el = ET.SubElement(parent, "PictureObject")
        el.set("Name", self.name("Picture"))
        left = 0.0
        if block.get("align") == "Center":
            left = max((width - block["width"]) / 2.0, 0.0)
        elif block.get("align") == "Right":
            left = max(width - block["width"], 0.0)
        el.set("Left", _num(left))
        el.set("Top", _num(y))
        el.set("Width", _num(block["width"]))
        el.set("Height", _num(block["height"]))
        el.set("SizeMode", "Stretch")
        el.set("Image", block["data"])
        return block["height"]

    def table(self, parent, block, y, width):
        cols = list(block["cols"]) or [width]
        scale = width / sum(cols) if sum(cols) > width else 1.0
        cols = [c * scale for c in cols]
        el = ET.SubElement(parent, "TableObject")
        el.set("Name", self.name("Table"))
        el.set("Left", "0")
        el.set("Top", _num(y))
        el.set("Width", _num(sum(cols)))
        for c in cols:
            col = ET.SubElement(el, "TableColumn")
            col.set("Name", self.name("Column"))
            col.set("Width", _num(c))

        total = 0.0
        for row in block["rows"]:
            row_el = ET.SubElement(el, "TableRow")
            row_el.set("Name", self.name("Row"))
            height = row.get("height") or 0.0
            index = 0
            for item in row["cells"]:
                span = max(1, int(item.get("colspan", 1)))
                cell_width = sum(cols[index:index + span]) or cols[-1]
                base = uniform_font(item["runs"])
                need = measure_runs(item["runs"], cell_width, base)
                height = max(height, need)
                index += span
            row_el.set("Height", _num(height))
            row_el.set("AutoSize", "true")
            total += height

            index = 0
            for item in row["cells"]:
                cell_el = ET.SubElement(row_el, "TableCell")
                cell_el.set("Name", self.name("Cell"))
                span = max(1, int(item.get("colspan", 1)))
                if span > 1:
                    cell_el.set("ColSpan", str(span))
                if int(item.get("rowspan", 1)) > 1:
                    cell_el.set("RowSpan", str(int(item["rowspan"])))
                base = uniform_font(item["runs"])
                _set_font(cell_el, base)
                _set_borders(cell_el, item.get("borders"),
                             item.get("border_color", "000000"),
                             item.get("border_width", 1.0))
                if item.get("align", "Left") != "Left":
                    cell_el.set("HorzAlign", item["align"])
                if item.get("valign", "Top") != "Top":
                    cell_el.set("VertAlign", item["valign"])
                if item.get("fill"):
                    cell_el.set("Fill.Color", format_color(item["fill"]))
                _set_text(cell_el, item["runs"], base)
                index += span
        el.set("Height", _num(total))
        return total

    def absolute(self, parent, block):
        """Блок с готовыми координатами (приходит из PDF)."""
        el = ET.SubElement(parent, "TextObject")
        el.set("Name", self.name("Text"))
        el.set("Left", _num(block["x"]))
        el.set("Top", _num(block["y"]))
        el.set("Width", _num(block["w"]))
        el.set("Height", _num(block["h"]))
        el.set("CanGrow", "true")
        if block.get("align", "Left") != "Left":
            el.set("HorzAlign", block["align"])
        if block.get("valign", "Top") != "Top":
            el.set("VertAlign", block["valign"])
        base = uniform_font(block["runs"])
        _set_font(el, base)
        _set_borders(el, block.get("borders"),
                     block.get("border_color", "000000"),
                     block.get("border_width", 1.0))
        if block.get("fill"):
            el.set("Fill.Color", format_color(block["fill"]))
        _set_text(el, block["runs"], base)
        return block["h"]

    def emit(self, parent, blocks, width, y=0.0):
        for block in blocks:
            kind = block["type"]
            if kind == "space":
                y += block["height"]
            elif kind == "p":
                y += block.get("space_before", 0.0)
                y += self.paragraph(parent, block, y, width)
                y += block.get("space_after", 0.0)
            elif kind == "table":
                y += self.table(parent, block, y, width)
            elif kind == "image":
                y += self.image(parent, block, y, width)
            elif kind == "abs":
                self.absolute(parent, block)
                y = max(y, block["y"] + block["h"])
            else:
                self.warnings.append("блок %s пропущен" % kind)
        return y


def build_report(doc, warnings):
    root = ET.Element("Report")
    root.set("ScriptLanguage", "CSharp")
    root.set("ReportInfo.Creator", CREATOR)
    root.set("ReportInfo.CreatorVersion", "2022.3.12.0")
    ET.SubElement(root, "Dictionary")

    builder = Builder(warnings)
    for index, sec in enumerate(doc["sections"]):
        page = ET.SubElement(root, "ReportPage")
        page.set("Name", "Page%d" % (index + 1))
        width_mm = sec["width"] / MM_TO_UNIT
        height_mm = sec["height"] / MM_TO_UNIT
        if sec.get("landscape"):
            page.set("Landscape", "true")
            width_mm, height_mm = height_mm, width_mm
        page.set("PaperWidth", _num(width_mm))
        page.set("PaperHeight", _num(height_mm))
        for key, attr in (("left", "LeftMargin"), ("right", "RightMargin"),
                          ("top", "TopMargin"), ("bottom", "BottomMargin")):
            page.set(attr, _num(sec["margins"][key] / MM_TO_UNIT))
        body_width = (sec["width"] - sec["margins"]["left"]
                      - sec["margins"]["right"])

        top = 0.0
        if sec["header"]:
            band = ET.SubElement(page, "PageHeaderBand")
            band.set("Name", builder.name("PageHeader"))
            band.set("Width", _num(body_width))
            height = builder.emit(band, sec["header"], body_width)
            band.set("Height", _num(height))
            top += height + 4

        band = ET.SubElement(page, "DataBand")
        band.set("Name", builder.name("Data"))
        band.set("Top", _num(top))
        band.set("Width", _num(body_width))
        band.set("CanGrow", "true")
        height = builder.emit(band, sec["body"], body_width)
        band.set("Height", _num(max(height, 10.0)))
        top += height + 4

        if sec["footer"]:
            foot = ET.SubElement(page, "PageFooterBand")
            foot.set("Name", builder.name("PageFooter"))
            foot.set("Top", _num(top))
            foot.set("Width", _num(body_width))
            fheight = builder.emit(foot, sec["footer"], body_width)
            foot.set("Height", _num(fheight))
    return root


def write_frx(doc, path, warnings):
    root = build_report(doc, warnings)
    _indent(root)
    body = ET.tostring(root, encoding="unicode")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
        fh.write(body)
        fh.write("\n")
    return path


def _indent(el, level=0):
    pad = "\n" + "  " * level
    if len(el):
        if not (el.text or "").strip():
            el.text = pad + "  "
        for child in el:
            _indent(child, level + 1)
        if not (child.tail or "").strip():
            child.tail = pad
    if level and not (el.tail or "").strip():
        el.tail = pad
