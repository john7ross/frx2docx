# -*- coding: utf-8 -*-
"""Чтение .docx в модель документа (обратный путь)."""

from __future__ import annotations

import base64

from docx import Document
from docx.oxml.ns import qn

from . import doctree
from .common import UNIT_TO_DXA

EMU_PER_UNIT = 9525.0          # 914400 EMU/дюйм / 96 units/дюйм
ALIGN_BY_VALUE = {"left": "Left", "center": "Center", "right": "Right",
                  "both": "Justify", "justify": "Justify",
                  "distribute": "Justify"}
VALIGN_BY_VALUE = {"top": "Top", "center": "Center", "bottom": "Bottom"}
BORDER_NONE = ("nil", "none")


def _units(emu):
    return float(emu) / EMU_PER_UNIT if emu is not None else 0.0


def _twips(value, default=0.0):
    try:
        return float(value) / UNIT_TO_DXA
    except (TypeError, ValueError):
        return default


def _style_table(document):
    """styleId -> оформление, с разворотом цепочки basedOn.

    Без этого заголовки и любые стилевые начертания теряются: в w:r их нет,
    они живут в styles.xml."""
    root = document.styles.element
    raw, order = {}, []
    for style in root.findall(qn("w:style")):
        style_id = style.get(qn("w:styleId"))
        if not style_id:
            continue
        based = style.find(qn("w:basedOn"))
        item = {"base": based.get(qn("w:val")) if based is not None else None,
                "run": _run_props(style.find(qn("w:rPr"))),
                "align": _align_of(style.find(qn("w:pPr")))}
        raw[style_id] = item
        order.append(style_id)

    defaults = {"run": {}, "align": None, "base": None}
    doc_defaults = root.find(qn("w:docDefaults"))
    if doc_defaults is not None:
        r_default = doc_defaults.find(qn("w:rPrDefault"))
        if r_default is not None:
            defaults["run"] = _run_props(r_default.find(qn("w:rPr")))

    resolved = {}

    def resolve(style_id, depth=0):
        if style_id in resolved:
            return resolved[style_id]
        item = raw.get(style_id)
        if item is None or depth > 16:
            return dict(defaults["run"]), defaults["align"]
        parent_run, parent_align = (resolve(item["base"], depth + 1)
                                    if item["base"] else
                                    (dict(defaults["run"]), defaults["align"]))
        run = dict(parent_run)
        run.update(item["run"])
        align = item["align"] or parent_align
        resolved[style_id] = (run, align)
        return resolved[style_id]

    table = {"": (dict(defaults["run"]), defaults["align"])}
    for style_id in order:
        table[style_id] = resolve(style_id)
    return table


def _run_props(r_pr):
    if r_pr is None:
        return {}
    out = {}
    for tag, key in (("w:b", "bold"), ("w:i", "italic"),
                     ("w:strike", "strike")):
        node = r_pr.find(qn(tag))
        if node is not None:
            out[key] = node.get(qn("w:val")) not in ("0", "false")
    u = r_pr.find(qn("w:u"))
    if u is not None:
        out["underline"] = u.get(qn("w:val")) not in ("none",)
    sz = r_pr.find(qn("w:sz"))
    if sz is not None and sz.get(qn("w:val")):
        out["size"] = float(sz.get(qn("w:val"))) / 2.0
    rfonts = r_pr.find(qn("w:rFonts"))
    if rfonts is not None:
        face = (rfonts.get(qn("w:ascii")) or rfonts.get(qn("w:hAnsi"))
                or rfonts.get(qn("w:cs")))
        if face:
            out["face"] = face
    color = r_pr.find(qn("w:color"))
    if color is not None:
        value = color.get(qn("w:val"))
        if value and value.lower() not in ("auto", "000000"):
            out["color"] = value.upper()
    return out


def _align_of(p_pr):
    if p_pr is None:
        return None
    jc = p_pr.find(qn("w:jc"))
    if jc is None:
        return None
    return ALIGN_BY_VALUE.get(jc.get(qn("w:val")))


def _paragraph_style(p, styles):
    p_pr = p.find(qn("w:pPr"))
    style_id = ""
    if p_pr is not None:
        node = p_pr.find(qn("w:pStyle"))
        if node is not None:
            style_id = node.get(qn("w:val")) or ""
    return styles.get(style_id, styles.get("", ({}, None)))


def read_docx(path, warnings):
    document = Document(path)
    try:
        styles = _style_table(document)
    except Exception as exc:                                   # noqa: BLE001
        warnings.append("стили документа не разобраны: %s" % exc)
        styles = {"": ({}, None)}
    doc = doctree.document()
    for index, sec in enumerate(document.sections):
        node = doctree.section(
            width=_units(sec.page_width), height=_units(sec.page_height),
            margins={"left": _units(sec.left_margin),
                     "right": _units(sec.right_margin),
                     "top": _units(sec.top_margin),
                     "bottom": _units(sec.bottom_margin)},
            landscape=sec.page_width > sec.page_height)
        if node["landscape"]:
            node["width"], node["height"] = node["height"], node["width"]
        doc["sections"].append(node)
        try:
            node["header"] = _read_part(sec.header, document, warnings, styles)
            node["footer"] = _read_part(sec.footer, document, warnings, styles)
        except Exception as exc:                               # noqa: BLE001
            warnings.append("колонтитул секции %d не прочитан: %s"
                            % (index + 1, exc))

    if not doc["sections"]:
        doc["sections"].append(doctree.section())

    bodies = _split_body(document, len(doc["sections"]), warnings, styles)
    for node, blocks in zip(doc["sections"], bodies):
        node["body"] = blocks
    return doc


def _split_body(document, count, warnings, styles=None):
    """Тело документа режется на секции по разрывам w:sectPr."""
    parts = [[]]
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            parts[-1].extend(_paragraph(child, document, warnings, styles))
            p_pr = child.find(qn("w:pPr"))
            if p_pr is not None and p_pr.find(qn("w:sectPr")) is not None:
                parts.append([])
        elif child.tag == qn("w:tbl"):
            parts[-1].append(_table(child, document, warnings, styles))
    while len(parts) < count:
        parts.append([])
    if len(parts) > count:
        tail = []
        for extra in parts[count:]:
            tail.extend(extra)
        parts = parts[:count]
        parts[-1].extend(tail)
    return parts


def _read_part(part, document, warnings, styles=None):
    blocks = []
    for child in part._element.iterchildren():
        if child.tag == qn("w:p"):
            blocks.extend(_paragraph(child, document, warnings, styles))
        elif child.tag == qn("w:tbl"):
            blocks.append(_table(child, document, warnings, styles))
    while blocks and blocks[-1]["type"] == "space":
        blocks.pop()
    return blocks


# --------------------------------------------------------------------------
# абзацы
# --------------------------------------------------------------------------
def _paragraph(p, document, warnings, styles=None):
    """Абзац -> список блоков: картинки выносятся отдельными блоками."""
    style_run, style_align = _paragraph_style(p, styles or {"": ({}, None)})
    runs, images = _runs(p, document, warnings, style_run)
    text = "".join(r["text"] for r in runs)
    fmt = _paragraph_format(p)
    if style_align and fmt["align"] == "Left":
        fmt["align"] = style_align
    blocks = []
    if text.strip():
        blocks.append(doctree.paragraph(runs, **fmt))
    blocks.extend(images)
    if not blocks:
        blocks.append(doctree.space(_empty_height(p)))
    return blocks


def _empty_height(p):
    size = None
    for r in p.findall(qn("w:r")):
        r_pr = r.find(qn("w:rPr"))
        if r_pr is not None:
            sz = r_pr.find(qn("w:sz"))
            if sz is not None:
                size = float(sz.get(qn("w:val"))) / 2.0
    return doctree.pt((size or 11.0) * 1.2)


def _paragraph_format(p):
    fmt = {"align": "Left", "indent": 0.0, "space_before": 0.0,
           "space_after": 0.0, "line_height": None}
    p_pr = p.find(qn("w:pPr"))
    if p_pr is None:
        return fmt
    jc = p_pr.find(qn("w:jc"))
    if jc is not None:
        fmt["align"] = ALIGN_BY_VALUE.get(jc.get(qn("w:val")), "Left")
    ind = p_pr.find(qn("w:ind"))
    if ind is not None:
        first = ind.get(qn("w:firstLine"))
        if first:
            fmt["indent"] = _twips(first)
    spacing = p_pr.find(qn("w:spacing"))
    if spacing is not None:
        fmt["space_before"] = _twips(spacing.get(qn("w:before")), 0.0)
        fmt["space_after"] = _twips(spacing.get(qn("w:after")), 0.0)
        line = spacing.get(qn("w:line"))
        rule = spacing.get(qn("w:lineRule"))
        if line and rule in ("exact", "atLeast"):
            fmt["line_height"] = _twips(line)
    return fmt


# контейнеры, внутрь которых спускаемся за текстом
INLINE_CONTAINERS = (qn("w:hyperlink"), qn("w:ins"), qn("w:smartTag"),
                     qn("w:sdt"), qn("w:sdtContent"), qn("w:bdo"),
                     qn("w:dir"))


def _runs(p, document, warnings, style_run=None):
    """Фрагменты абзаца и картинки. Внутрь w:pict (водяные знаки, надписи)
    не заходим: это оформление страницы, а не текст абзаца."""
    runs, images = [], []
    style_run = style_run or {}

    def walk(node):
        for child in node.iterchildren():
            if child.tag == qn("w:r"):
                if child.find(qn("w:pict")) is not None:
                    continue
                picture = _picture(child, document, warnings)
                if picture:
                    images.append(picture)
                    continue
                text = _run_text(child)
                if text:
                    runs.append(_style_of(child, text, style_run))
            elif child.tag == qn("w:fldSimple"):
                instr = (child.get(qn("w:instr")) or "").upper()
                token = ("[Page]" if "PAGE" in instr and "NUMPAGES" not in instr
                         else "[TotalPages]" if "NUMPAGES" in instr else "")
                if token:
                    runs.append(doctree.run(token))
            elif child.tag in INLINE_CONTAINERS:
                walk(child)

    walk(p)
    return _merge(runs), images


def _run_text(r):
    out = []
    for node in r.iterchildren():
        if node.tag == qn("w:t"):
            out.append(node.text or "")
        elif node.tag == qn("w:tab"):
            out.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            out.append("\n")
        elif node.tag == qn("w:noBreakHyphen"):
            out.append("-")
    return "".join(out)


def _style_of(r, text, style_run=None):
    """Оформление фрагмента: стиль абзаца, поверх — явные свойства прогона."""
    frag = doctree.run(text)
    frag.update(style_run or {})
    frag.update(_run_props(r.find(qn("w:rPr"))))
    frag["text"] = text
    return frag


def _merge(runs):
    out = []
    for frag in runs:
        if out and all(out[-1][k] == frag[k] for k in
                       ("bold", "italic", "underline", "strike", "size",
                        "face", "color")):
            out[-1]["text"] += frag["text"]
        else:
            out.append(frag)
    return out


def _picture(r, document, warnings):
    blips = r.findall(".//" + qn("a:blip"))
    if not blips:
        return None
    rid = blips[0].get(qn("r:embed"))
    if not rid:
        return None
    try:
        part = document.part.related_parts[rid]
        blob = part.blob
    except Exception as exc:                                   # noqa: BLE001
        warnings.append("картинка %s не прочитана: %s" % (rid, exc))
        return None
    extent = r.findall(".//" + qn("wp:extent"))
    if extent:
        width = _units(int(extent[0].get("cx")))
        height = _units(int(extent[0].get("cy")))
    else:
        width = height = 96.0
    return doctree.image(base64.b64encode(blob).decode(), width, height)


# --------------------------------------------------------------------------
# таблицы
# --------------------------------------------------------------------------
def _table(tbl, document, warnings, styles=None):
    grid = tbl.find(qn("w:tblGrid"))
    cols = []
    if grid is not None:
        for gc in grid.findall(qn("w:gridCol")):
            cols.append(_twips(gc.get(qn("w:w")), 60.0))
    rows_xml = tbl.findall(qn("w:tr"))
    rows = []
    pending = {}                       # колонка -> ячейка с вертикальным слиянием
    for r_index, tr in enumerate(rows_xml):
        cells = []
        column = 0
        for tc in tr.findall(qn("w:tc")):
            tc_pr = tc.find(qn("w:tcPr"))
            span = 1
            if tc_pr is not None:
                gs = tc_pr.find(qn("w:gridSpan"))
                if gs is not None:
                    span = max(1, int(gs.get(qn("w:val")) or 1))
            merge = None
            if tc_pr is not None:
                v = tc_pr.find(qn("w:vMerge"))
                if v is not None:
                    merge = v.get(qn("w:val")) or "continue"
            if merge == "continue" and column in pending:
                pending[column]["rowspan"] += 1
                column += span
                continue
            item = _cell(tc, tc_pr, span, document, warnings, styles)
            if merge == "restart":
                pending[column] = item
            elif column in pending:
                del pending[column]
            cells.append(item)
            column += span
        height = 0.0
        tr_pr = tr.find(qn("w:trPr"))
        if tr_pr is not None:
            h = tr_pr.find(qn("w:trHeight"))
            if h is not None:
                height = _twips(h.get(qn("w:val")), 0.0)
        rows.append({"height": height, "cells": cells})
    if not cols:
        cols = [60.0] * max((len(r["cells"]) for r in rows), default=1)
    return doctree.table(cols, rows)


def _cell(tc, tc_pr, span, document, warnings, styles=None):
    runs = []
    align = "Left"
    for p in tc.findall(qn("w:p")):
        style_run, _ = _paragraph_style(p, styles or {"": ({}, None)})
        part, _images = _runs(p, document, warnings, style_run)
        if runs and part:
            runs.append(doctree.run("\n"))
        runs.extend(part)
        fmt = _paragraph_format(p)
        if fmt["align"] != "Left" and align == "Left":
            align = fmt["align"]
    borders = {"t": 0, "r": 0, "b": 0, "l": 0}
    color, width, fill, valign = "000000", 1.0, None, "Top"
    if tc_pr is not None:
        tc_borders = tc_pr.find(qn("w:tcBorders"))
        if tc_borders is not None:
            for side, key in (("top", "t"), ("left", "l"), ("bottom", "b"),
                              ("right", "r")):
                node = tc_borders.find(qn("w:" + side))
                if node is None:
                    continue
                if node.get(qn("w:val")) not in BORDER_NONE:
                    borders[key] = 1
                    if node.get(qn("w:color")) not in (None, "auto"):
                        color = node.get(qn("w:color")).upper()
                    sz = node.get(qn("w:sz"))
                    if sz:
                        width = max(float(sz) / 6.0, 0.5)
        shd = tc_pr.find(qn("w:shd"))
        if shd is not None:
            value = shd.get(qn("w:fill"))
            if value and value.lower() not in ("auto", "ffffff"):
                fill = value.upper()
        v = tc_pr.find(qn("w:vAlign"))
        if v is not None:
            valign = VALIGN_BY_VALUE.get(v.get(qn("w:val")), "Top")
    return doctree.cell(runs or [doctree.run("")], colspan=span, align=align,
                        valign=valign, borders=borders, fill=fill,
                        border_color=color, border_width=width)
