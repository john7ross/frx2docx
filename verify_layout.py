#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_layout.py — проверка, что вёрстка не поехала.

Берёт исходный .frx и полученный из него .pdf и сравнивает, на каком
расстоянии от левого края страницы стоит каждая надпись: в шаблоне
(по координатам FastReport) и в готовом PDF (по координатам глифов).

Запуск:
    python verify_layout.py template.frx template.pdf
    python verify_layout.py papka_s_frx papka_s_pdf

Внешние программы не нужны: PDF разбирается своим парсером (frxkit.pdfread).

Что показывает:
    найдено   — сколько надписей удалось сопоставить (порядок учитывается)
    сдвиг     — медиана и максимум расхождения по горизонтали, в мм
    хвост     — сколько надписей уехало больше чем на 3 мм
Нормальный результат: медиана до ~1 мм, хвост близок к нулю.
Крупные сдвиги = сетка колонок собралась не так, стоит посмотреть глазами.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frxkit import frxread as F                               # noqa: E402
from frxkit import pdfparse, pdfread                          # noqa: E402

PT_PER_UNIT = 72.0 / 96.0
PT_PER_MM = 72.0 / 25.4


def anchors(frx_path):
    """Статические надписи шаблона в порядке чтения + ожидаемый отступ, pt."""
    root = F.read_frx(frx_path)
    items = []
    warn = []
    for page_no, page in enumerate(F.report_pages(root, warn)):
        _, _, margins, body = F.page_geometry(page, warn)
        left_pt = margins["left"] / 20.0        # dxa -> pt
        for band in F.collect_bands(page, warn, set()):
            for o in band["objs"]:
                if (o["x"] + o["w"] <= 0.5 or o["y"] + o["h"] <= 0.5
                        or o["x"] >= body - 0.5):
                    continue
                raw = o["text"]
                text = re.sub(r"\s+", " ", raw).strip()
                if not text or "[" in text:
                    continue
                if o["align"] not in ("Left", "Justify"):
                    continue                     # центр/право сравнивать нечем
                if raw[:1].isspace() or o.get("indent"):
                    continue        # красная строка — сравнивать не с чем
                if len(text) < 10 or len(text.split()) < 2:
                    continue        # короткие надписи ловятся не в том месте
                items.append({
                    "page": page_no,
                    "order": (page_no, band["top"] + o["y"], o["x"]),
                    "text": text,
                    "expect_pt": left_pt + max(o["x"], 0.0) * PT_PER_UNIT,
                })
    items.sort(key=lambda d: d["order"])
    return items


def pdf_words(pdf_path):
    """Слова PDF в порядке чтения: (страница, xMin_pt, текст).

    Word режет строку на десятки кусочков ради кернинга, поэтому строку
    сначала собираем целиком с координатой каждого символа, и уже потом
    делим на слова."""
    doc = pdfparse.load(pdf_path)
    words = []
    warn = []
    for page_no, page in enumerate(doc.pages()):
        reader = pdfread.ContentReader(doc, page, warn).run(doc.content(page))
        for line in pdfread.group_lines(reader.items):
            chars = []
            previous_end = None
            for item in line["items"]:
                text = item["text"]
                if previous_end is not None and not text.startswith(" ") \
                        and item["x"] - previous_end > item["size"] * 0.16:
                    chars.append((" ", previous_end))
                step = item["width"] / max(len(text), 1)
                for i, ch in enumerate(text):
                    chars.append((ch, item["x"] + i * step))
                previous_end = item["x"] + item["width"]
            token, start = "", None
            for ch, x in chars + [(" ", 0.0)]:
                if ch.isspace():
                    if token:
                        words.append((page_no, start, token))
                    token, start = "", None
                else:
                    if not token:
                        start = x
                    token += ch
    return words


def compare(frx_path, pdf_path):
    items = anchors(frx_path)
    words = pdf_words(pdf_path)
    cursor = 0
    deltas = []
    matched = 0
    worst = []

    for item in items:
        parts = item["text"].split()
        head = parts[:3] if len(parts) >= 3 else parts[:2]
        found = -1
        for i in range(cursor, len(words) - len(head) + 1):
            if all(words[i + k][2].startswith(head[k][:12])
                   for k in range(len(head))):
                found = i
                break
        if found < 0:
            continue
        matched += 1
        cursor = found + 1
        delta_mm = (words[found][1] - item["expect_pt"]) / PT_PER_MM
        deltas.append(abs(delta_mm))
        worst.append((abs(delta_mm), item["text"][:45], delta_mm))

    worst.sort(reverse=True)
    return items, matched, deltas, worst[:3]


def median(values):
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Сверка положения надписей в шаблоне и в готовом PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("frx", help="файл .frx или папка с ними")
    ap.add_argument("pdf", help="файл .pdf или папка с ними")
    ap.add_argument("--tolerance", type=float, default=3.0,
                    help="порог «хвоста» в мм (по умолчанию 3)")
    args = ap.parse_args(argv)

    if os.path.isdir(args.frx):
        pairs = []
        for f in sorted(glob.glob(os.path.join(args.frx, "*.frx"))):
            name = os.path.splitext(os.path.basename(f))[0]
            p = os.path.join(args.pdf, name + ".pdf")
            if os.path.exists(p):
                pairs.append((f, p))
    else:
        pairs = [(args.frx, args.pdf)]

    if not pairs:
        print("Нечего сравнивать: не нашлось пар .frx + .pdf")
        return 2

    print("%-24s %7s %8s %9s %9s %s" %
          ("файл", "надп.", "найдено", "медиана", "максимум", "хвост"))
    bad_total = 0
    for frx, pdf in pairs:
        name = os.path.splitext(os.path.basename(frx))[0]
        try:
            items, matched, deltas, worst = compare(frx, pdf)
        except Exception as exc:                              # noqa: BLE001
            print("%-24s ОШИБКА: %s" % (name, exc))
            bad_total += 1
            continue
        tail = sum(1 for d in deltas if d > args.tolerance)
        bad_total += tail
        print("%-24s %7d %8d %8.2f мм %6.2f мм %d" %
              (name, len(items), matched, median(deltas),
               max(deltas) if deltas else 0.0, tail))
        if tail:
            for _, text, signed in worst:
                print("        уехало на %+.1f мм: %s" % (signed, text))
    print("\nнадписей за порогом %.1f мм: %d" % (args.tolerance, bad_total))
    return 0 if bad_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
