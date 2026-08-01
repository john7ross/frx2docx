# -*- coding: utf-8 -*-
"""Разбор командной строки и оркестровка конвертации в обе стороны."""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile

from . import __version__

FORWARD_EXT = {".frx"}
REVERSE_EXT = {".docx", ".md", ".markdown", ".txt", ".pdf"}
ALL_EXT = FORWARD_EXT | REVERSE_EXT

EPILOG = """
Примеры:
    frx2docx template.frx                  шаблон -> Word
    frx2docx template.frx --format both    шаблон -> Word и PDF
    frx2docx C:\\templates -r --format pdf  папка целиком -> PDF
    frx2docx договор.docx                  текст -> шаблон FastReport
    frx2docx договор.pdf --format frx      PDF  -> шаблон FastReport

Направление определяется по расширению: .frx конвертируется в документ,
.docx / .md / .txt / .pdf — обратно в шаблон .frx.
"""


# --------------------------------------------------------------------------
# ввод
# --------------------------------------------------------------------------
def expand_inputs(items, recursive):
    files = []
    for item in items:
        if os.path.isdir(item):
            pattern = "**/*" if recursive else "*"
            found = glob.glob(os.path.join(item, pattern), recursive=recursive)
            files.extend(sorted(f for f in found
                                if os.path.splitext(f)[1].lower() in ALL_EXT))
        elif any(ch in item for ch in "*?["):
            files.extend(sorted(glob.glob(item, recursive=recursive)))
        else:
            files.append(item)
    seen, result = set(), []
    for f in files:
        key = os.path.abspath(f).lower()
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def report(warnings, verbose, limit=5):
    if not warnings:
        return
    uniq = list(dict.fromkeys(warnings))
    shown = uniq if verbose else uniq[:limit]
    for w in shown:
        print("      ! %s" % w)
    if len(uniq) > len(shown):
        print("      ! ещё %d предупреждений (-v — показать все)"
              % (len(uniq) - len(shown)))


# --------------------------------------------------------------------------
# прямой путь: .frx -> .docx / .pdf
# --------------------------------------------------------------------------
def frx_to_docx(src, docx_path, verbose, include_hidden=False):
    from .docxwrite import build_document
    from .frxread import page_info, read_frx, report_pages

    warnings = []
    root = read_frx(src)
    base_dir = os.path.dirname(os.path.abspath(src))
    pages = report_pages(root, warnings, include_hidden)
    if not pages:
        raise ValueError("в файле нет ни одной видимой <ReportPage>")
    seen = set()
    infos = [page_info(p, warnings, seen, base_dir) for p in pages]
    document = build_document(infos, warnings)
    os.makedirs(os.path.dirname(os.path.abspath(docx_path)), exist_ok=True)
    document.save(docx_path)
    report(warnings, verbose)
    return docx_path


def frx_to_pdf_direct(src, pdf_path, verbose, include_hidden=False):
    """Встроенный движок: PDF рисуется из той же модели, что и docx."""
    from .frxread import page_info, read_frx, report_pages
    from .pdfwrite import build_pdf

    warnings = []
    root = read_frx(src)
    base_dir = os.path.dirname(os.path.abspath(src))
    pages = report_pages(root, warnings, include_hidden)
    if not pages:
        raise ValueError("в файле нет ни одной видимой <ReportPage>")
    seen = set()
    infos = [page_info(p, warnings, seen, base_dir) for p in pages]
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    build_pdf(infos, pdf_path, warnings)
    report(warnings, verbose)
    return pdf_path


# --------------------------------------------------------------------------
# обратный путь: документ -> .frx
# --------------------------------------------------------------------------
def to_frx(src, frx_path, verbose):
    from .frxwrite import write_frx

    ext = os.path.splitext(src)[1].lower()
    warnings = []
    if ext == ".docx":
        from .docxread import read_docx
        doc = read_docx(src, warnings)
    elif ext == ".pdf":
        from .pdfread import read_pdf
        doc = read_pdf(src, warnings)
    else:
        from .textread import read_text
        doc = read_text(src, warnings)
    os.makedirs(os.path.dirname(os.path.abspath(frx_path)), exist_ok=True)
    write_frx(doc, frx_path, warnings)
    report(warnings, verbose)
    return frx_path


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog="frx2docx",
        description="Конвертер шаблонов FastReport: .frx <-> .docx / .pdf / .md / .txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG)
    ap.add_argument("input", nargs="+", help="файл, маска или папка")
    ap.add_argument("-o", "--outdir", default=None,
                    help="папка для результата (по умолчанию — рядом с исходником)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="искать файлы в подпапках")
    ap.add_argument("-f", "--format", choices=("docx", "pdf", "both", "frx"),
                    default=None,
                    help="что получить: docx, pdf, both или frx "
                         "(по умолчанию docx для .frx и frx для остальных)")
    ap.add_argument("--pdf", action="store_true",
                    help="то же, что --format both")
    ap.add_argument("--engine", choices=("auto", "word", "libreoffice",
                                         "builtin"),
                    default="auto",
                    help="чем делать PDF: auto (Word/LibreOffice, иначе "
                         "встроенный), word, libreoffice или builtin")
    ap.add_argument("--all-pages", action="store_true",
                    help="переносить и страницы с Visible=false")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="показывать все предупреждения и трассировки ошибок")
    ap.add_argument("--version", action="version",
                    version="frx2docx %s" % __version__)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:                                   # русский текст в cp866-консоли
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    files = expand_inputs(args.input, args.recursive)
    if not files:
        print("Не найдено ни одного подходящего файла "
              "(.frx, .docx, .md, .txt, .pdf)")
        return 2

    forward = [f for f in files if os.path.splitext(f)[1].lower() in FORWARD_EXT]
    reverse = [f for f in files if os.path.splitext(f)[1].lower() in REVERSE_EXT]
    unknown = [f for f in files
               if os.path.splitext(f)[1].lower() not in ALL_EXT]
    for f in unknown:
        print("%s\n  пропущен: неизвестное расширение" % f)

    ok = 0
    total = len(forward) + len(reverse)
    if reverse:
        ok += run_reverse(reverse, args)
    if forward:
        ok += run_forward(forward, args)

    print("\nГотово: %d из %d" % (ok, total))
    return 0 if ok == total and total else 1


def unique(path, taken):
    """Два исходника с одним именем не должны затирать друг друга."""
    if path.lower() not in taken:
        taken.add(path.lower())
        return path
    stem, ext = os.path.splitext(path)
    index = 2
    while "%s-%d%s" % (stem, index, ext) in taken:
        index += 1
    result = "%s-%d%s" % (stem, index, ext)
    taken.add(result.lower())
    return result


def run_reverse(files, args):
    ok = 0
    taken = set()
    for src in files:
        print("%s" % src)
        if not os.path.exists(src):
            print("  файл не найден")
            continue
        target_dir = args.outdir or os.path.dirname(os.path.abspath(src))
        name = os.path.splitext(os.path.basename(src))[0]
        dst = unique(os.path.join(target_dir, name + ".frx"), taken)
        try:
            to_frx(src, dst, args.verbose)
            print("  OK  %s" % dst)
            ok += 1
        except Exception as exc:                              # noqa: BLE001
            print("  ОШИБКА: %s: %s" % (type(exc).__name__, exc))
            if args.verbose:
                import traceback
                traceback.print_exc()
    return ok


def run_forward(files, args):
    from .pdfconv import convert as external_pdf

    fmt = args.format or "docx"
    if fmt == "frx":
        print("  для .frx направление 'frx' не имеет смысла — беру docx")
        fmt = "docx"
    if args.pdf and fmt == "docx":
        fmt = "both"
    want_pdf = fmt in ("pdf", "both")
    keep_docx = fmt in ("docx", "both")
    builtin_only = args.engine == "builtin"

    scratch = None
    if not keep_docx and not builtin_only:
        scratch = tempfile.mkdtemp(prefix="frx2docx_")

    ok = 0
    pdf_jobs = []
    taken = set()
    try:
        for src in files:
            print("%s" % src)
            if not os.path.exists(src):
                print("  файл не найден")
                continue
            target_dir = args.outdir or os.path.dirname(os.path.abspath(src))
            name = os.path.splitext(os.path.basename(src))[0]
            try:
                if keep_docx or not builtin_only:
                    docx_path = unique(os.path.join(scratch or target_dir,
                                                    name + ".docx"), taken)
                    frx_to_docx(src, docx_path, args.verbose, args.all_pages)
                    if keep_docx:
                        print("  OK  %s" % docx_path)
                if want_pdf:
                    pdf_path = unique(os.path.join(target_dir, name + ".pdf"),
                                      taken)
                    if builtin_only:
                        frx_to_pdf_direct(src, pdf_path, args.verbose,
                                          args.all_pages)
                        print("  OK  %s  (встроенный движок)" % pdf_path)
                    else:
                        pdf_jobs.append((docx_path, pdf_path, src))
                ok += 1
            except Exception as exc:                          # noqa: BLE001
                print("  ОШИБКА: %s: %s" % (type(exc).__name__, exc))
                if args.verbose:
                    import traceback
                    traceback.print_exc()

        if pdf_jobs:
            print("\nСобираю PDF (%d шт., один запуск конвертера)..."
                  % len(pdf_jobs))
            pairs = [(d, p) for d, p, _ in pdf_jobs]
            done, used, errors = external_pdf(pairs, args.engine)
            fallback = []
            for docx_path, pdf_path, src in pdf_jobs:
                if done.get(pdf_path):
                    print("  OK  %s  (через %s)" % (pdf_path, done[pdf_path]))
                else:
                    fallback.append((src, pdf_path))
            if fallback:
                for e in dict.fromkeys(errors):
                    print("      внешний конвертер недоступен: %s" % e)
                print("      перехожу на встроенный движок PDF")
                for src, pdf_path in fallback:
                    try:
                        frx_to_pdf_direct(src, pdf_path, args.verbose,
                                          args.all_pages)
                        print("  OK  %s  (встроенный движок)" % pdf_path)
                    except Exception as exc:                  # noqa: BLE001
                        print("  PDF не создан: %s (%s)"
                              % (os.path.basename(pdf_path), exc))
                        ok -= 1
                        if args.verbose:
                            import traceback
                            traceback.print_exc()
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    return max(ok, 0)
