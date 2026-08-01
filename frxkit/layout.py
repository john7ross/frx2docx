# -*- coding: utf-8 -*-
"""Раскладка абсолютных прямоугольников в табличную сетку.

FastReport размещает объекты по координатам, Word и наш PDF-движок — потоком.
Общий знаменатель — таблица без видимых границ: колонки берутся из всех
уникальных X-координат объектов, строки — из Y. Объект занимает диапазон
ячеек, границы и заливка переносятся на ячейку.

На выходе — список блоков:
    {'type': 'table', 'cols': [...], 'row_heights': [...], 'spans': [...]}
    {'type': 'spacer', 'h': ...}
"""

from __future__ import annotations

from .common import GAP_SPLIT, XTOL, YTOL


def snap_values(values, tol):
    out = []
    for v in sorted(values):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def snap_to(v, grid, tol):
    best = min(grid, key=lambda g: abs(g - v))
    return best if abs(best - v) <= tol else v


def clip_overlaps(objs):
    """Подписи без рамок в конструкторе часто шире, чем нужно, и налезают
    на соседние объекты. Обрезаем их, чтобы сетка была непротиворечивой."""
    for a in objs:
        if sum(a["brd"].values()) or a.get("image"):
            continue
        right = a["x"] + a["w"]
        for b in objs:
            if b is a:
                continue
            overlap = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if overlap < 0.5 * a["h"]:
                continue
            if a["x"] + 1 < b["x"] < right - 1:
                right = b["x"]
        a["w"] = round(right - a["x"], 2)

    for a in objs:
        if sum(a["brd"].values()) or a.get("image"):
            continue
        bottom = a["y"] + a["h"]
        for b in objs:
            if b is a:
                continue
            overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            if overlap < 0.5 * a["w"]:
                continue
            if a["y"] + 1 < b["y"] < bottom - 1:
                bottom = b["y"]
        a["h"] = round(bottom - a["y"], 2)


def _area(o):
    return max(o["w"], 0.0) * max(o["h"], 0.0)


def extract_floats(objs, warnings):
    """Объекты, целиком лежащие поверх другого (заметки, наклейки поверх
    абзаца), в табличную сетку не укладываются — выносим их отдельно."""
    floats = []
    for b in list(objs):
        if _area(b) <= 0:
            continue
        for a in objs:
            if a is b or _area(a) <= _area(b):
                continue
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if ox <= 0 or oy <= 0:
                continue
            if ox * oy >= 0.7 * _area(b):
                floats.append(b)
                objs.remove(b)
                warnings.append(
                    "объект %s лежал поверх %s — вынесен отдельной строкой"
                    % (b["name"] or b["text"][:25], a["name"]))
                break
    return floats


def float_block(obj, page_width):
    left = max(obj["x"], 0.0)
    width = min(obj["w"], page_width - left)
    cols, index = [], 0
    if left > 0.5:
        cols.append(round(left, 2))
        index = 1
    cols.append(round(max(width, 1.0), 2))
    tail = page_width - left - width
    if tail > 0.5:
        cols.append(round(tail, 2))
    return {"type": "table", "cols": cols,
            "row_heights": [round(obj["h"], 2)],
            "spans": [(0, index, 1, 1, obj)],
            "y0": obj["y"], "y1": obj["y"] + obj["h"]}


def gridify(band, page_width, warnings):
    """Бэнд -> список блоков: {'table': cols/rows} и {'spacer': h}."""
    objs = []
    for o in band["objs"]:
        # FastReport «паркует» неиспользуемые объекты далеко за холстом
        if (o["x"] + o["w"] <= 0.5 or o["y"] + o["h"] <= 0.5
                or o["x"] >= page_width - 0.5):
            warnings.append("объект %s лежит за пределами страницы и пропущен"
                            % (o["name"] or o["text"][:25]))
            continue
        if o["x"] < 0:                      # частично за левым краем — подрезаем
            o["w"] = round(o["w"] + o["x"], 2)
            o["x"] = 0.0
        if o["y"] < 0:
            o["h"] = round(o["h"] + o["y"], 2)
            o["y"] = 0.0
        objs.append(o)
    if not objs:
        return []
    band["objs"] = objs
    clip_overlaps(objs)
    floats = extract_floats(objs, warnings)

    xs = snap_values([0.0, page_width] +
                     [o["x"] for o in objs] +
                     [min(o["x"] + o["w"], page_width) for o in objs], XTOL)
    xs = [x for x in xs if x <= page_width + XTOL]
    if xs[-1] < page_width:
        xs[-1] = page_width
    ys = snap_values([o["y"] for o in objs] +
                     [o["y"] + o["h"] for o in objs], YTOL)
    if len(xs) < 2 or len(ys) < 2:
        return []

    ncol, nrow = len(xs) - 1, len(ys) - 1
    grid = [[None] * ncol for _ in range(nrow)]

    def col_of(v):
        return min(range(ncol), key=lambda i: abs(xs[i] - v))

    def row_of(v):
        return min(range(nrow), key=lambda i: abs(ys[i] - v))

    for o in objs:
        x0 = snap_to(o["x"], xs, XTOL)
        x1 = snap_to(min(o["x"] + o["w"], page_width), xs, XTOL)
        y0 = snap_to(o["y"], ys, YTOL)
        y1 = snap_to(o["y"] + o["h"], ys, YTOL)
        c0 = col_of(x0)
        c1 = ncol if x1 >= xs[-1] else max(col_of(x1), c0 + 1)
        r0 = row_of(y0)
        r1 = nrow if y1 >= ys[-1] else max(row_of(y1), r0 + 1)
        cells_in_region = [(r, c)
                           for r in range(r0, min(r1, nrow))
                           for c in range(c0, min(c1, ncol))]
        if (cells_in_region and o["text"].strip()
                and all(grid[r][c] is not None for r, c in cells_in_region)
                and all(not grid[r][c][0]["text"].strip()
                        for r, c in cells_in_region)):
            # схлопнувшаяся строка-разделитель заняла место: пустое уступает
            for r, c in cells_in_region:
                grid[r][c] = None
        placed = False
        for r, c in cells_in_region:
            if grid[r][c] is None:
                grid[r][c] = (o, r0, c0, r1 - r0, c1 - c0)
                placed = True
        if not placed:
            warnings.append("объект %s перекрыт другим и не размещён" %
                            (o["name"] or o["text"][:30]))

    # режем бэнд на таблицы по крупным пустым промежуткам
    segments, current = [], []
    for r in range(nrow):
        empty = all(g is None for g in grid[r])
        h = ys[r + 1] - ys[r]
        if empty and h > GAP_SPLIT:
            if current:
                segments.append(("table", current))
                current = []
            segments.append(("spacer", (h, ys[r], ys[r + 1])))
        else:
            current.append(r)
    if current:
        segments.append(("table", current))

    blocks = []
    for kind, payload in segments:
        if kind == "spacer":
            h, y0, y1 = payload
            blocks.append({"type": "spacer", "h": round(h, 2),
                           "y0": y0, "y1": y1})
            continue
        rows_idx = payload

        # фактически занятые каждым объектом ячейки: номинальный span мог быть
        # урезан соседом, и merge по номиналу затёр бы чужую ячейку
        owned = []
        for ri, r in enumerate(rows_idx):
            for c in range(ncol):
                g = grid[r][c]
                if not g or g[1] != r or g[2] != c:
                    continue
                obj = g[0]
                c_end = c + 1
                while (c_end < ncol and grid[r][c_end] is not None
                       and grid[r][c_end][0] is obj):
                    c_end += 1
                r_end = ri + 1
                while (r_end < len(rows_idx)
                       and grid[rows_idx[r_end]][c] is not None
                       and grid[rows_idx[r_end]][c][0] is obj):
                    r_end += 1
                owned.append((ri, c, r_end - ri, c_end - c, obj))

        used = {0, ncol}
        for _, c, _, cs, _ in owned:
            used.add(c)
            used.add(c + cs)
        keep = sorted(used)
        colmap = {k: i for i, k in enumerate(keep)}
        cols = [round(xs[keep[i + 1]] - xs[keep[i]], 2)
                for i in range(len(keep) - 1)]
        nc = len(cols)

        spans = []
        for ri, c, rs, cs, obj in owned:
            lc = colmap.get(c)
            if lc is None:
                continue
            lc2 = colmap.get(c + cs, nc)
            spans.append((ri, lc, rs, max(lc2 - lc, 1), obj))

        table_rows = [round(ys[r + 1] - ys[r], 2) for r in rows_idx]
        blocks.append({"type": "table", "cols": cols,
                       "row_heights": table_rows, "spans": spans,
                       "y0": ys[rows_idx[0]], "y1": ys[rows_idx[-1] + 1]})

    for f in sorted(floats, key=lambda o: (o["y"], o["x"])):
        blk = float_block(f, page_width)
        anchor = f["y"] + f["h"] / 2.0
        pos = len(blocks)
        for i, b in enumerate(blocks):
            if b["y0"] >= anchor:
                pos = i
                break
        blocks.insert(pos, blk)
    return blocks


def band_width_of(bands, default):
    """Реальная ширина бэндов бывает меньше рабочей ширины страницы."""
    return max([max(o["x"] + o["w"] for o in b["objs"]) for b in bands],
               default=default)


def page_blocks(page, warnings):
    """Все блоки тела страницы плюс ширина, к которой они привязаны."""
    bands = page["body"]
    width = min(max(band_width_of(bands, page["body_units"]), 1.0),
                page["body_units"])
    blocks = []
    for band in bands:
        blocks.extend(gridify(band, width, warnings))
    return blocks, width


def part_blocks(bands, body_units, warnings):
    """Блоки колонтитула: своя ширина, чтобы не растягивать на всю страницу."""
    if not bands:
        return [], body_units
    width = min(max(band_width_of(bands, body_units), 1.0), body_units)
    blocks = []
    for band in bands:
        blocks.extend(gridify(band, width, warnings))
    return blocks, width
