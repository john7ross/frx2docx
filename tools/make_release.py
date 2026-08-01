# -*- coding: utf-8 -*-
"""Собирает архивы для релиза. Запуск:  python tools/make_release.py

Получается два файла в dist/:
    frx2docx-<версия>-portable.zip  папка целиком со встроенным Python
    frx2docx-<версия>-exe.zip       один frx2docx.exe плюс инструкции

Перед сборкой exe должен быть уже собран (СОБРАТЬ EXE.bat или PyInstaller).
"""

from __future__ import annotations

import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from frxkit import __version__                                  # noqa: E402

DIST = os.path.join(ROOT, "dist")

DOCS = ["README.md", "README.ru.md", "ARCHITECTURE.md", "ARCHITECTURE.ru.md",
        "CHANGELOG.md", "LICENSE", "requirements.txt", "КАК ПОЛЬЗОВАТЬСЯ.docx"]

# Шрифты внутри .exe, а SIL OFL требует, чтобы лицензия ехала вместе с ними
FONT_DOCS = ["fonts/LICENSE-Liberation.txt", "fonts/AUTHORS-Liberation.txt"]
SCRIPTS = ["frx2docx.py", "verify_layout.py"]
BATS = ["КОНВЕРТИРОВАТЬ.bat", "ПРОВЕРИТЬ ВЁРСТКУ.bat", "СОБРАТЬ EXE.bat",
        "УСТАНОВКА.bat", "ТЕСТЫ.bat"]
TREES = ["frxkit", "fonts", "tests", "tools", "python", "wheels"]
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo"}


def add_file(zf, path, arc):
    zf.write(path, arc)


def add_tree(zf, folder, prefix):
    root = os.path.join(ROOT, folder)
    if not os.path.isdir(root):
        print("  пропущено (нет папки):", folder)
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, ROOT)
            add_file(zf, full, os.path.join(prefix, rel))


def portable(path):
    top = "frx2docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in DOCS + SCRIPTS + BATS:
            full = os.path.join(ROOT, name)
            if os.path.exists(full):
                add_file(zf, full, os.path.join(top, name))
        for folder in TREES:
            add_tree(zf, folder, top)
        zf.writestr(os.path.join(top, "IN", "ПОЛОЖИТЕ СЮДА ФАЙЛЫ.nfo"),
                    _in_readme())
        zf.writestr(os.path.join(top, "OUT", ".gitkeep"), "")
    return path


def exe_only(path):
    top = "frx2docx"
    exe = os.path.join(DIST, "frx2docx.exe")
    if not os.path.exists(exe):
        print("  frx2docx.exe не собран — архив с exe пропущен")
        return None
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_file(zf, exe, os.path.join(top, "frx2docx.exe"))
        for name in DOCS + FONT_DOCS:
            full = os.path.join(ROOT, name)
            if os.path.exists(full):
                add_file(zf, full, os.path.join(top, name.replace("/", os.sep)))
        zf.writestr(os.path.join(top, "КАК ЗАПУСКАТЬ.txt"), _exe_readme())
    return path


def _in_readme():
    return ("Скопируйте в эту папку то, что нужно сконвертировать:\r\n\r\n"
            "  .frx                      -> получите Word и/или PDF\r\n"
            "  .docx / .pdf / .md / .txt -> получите шаблон FastReport .frx\r\n"
            "\r\nЗатем запустите КОНВЕРТИРОВАТЬ.bat в папке уровнем выше.\r\n"
            "Результат появится в папке OUT.\r\n").encode("utf-8")


def _exe_readme():
    return ("frx2docx %s\r\n"
            "\r\n"
            "Перетащите файлы прямо на frx2docx.exe:\r\n"
            "  .frx                      -> получится .docx\r\n"
            "  .docx / .pdf / .md / .txt -> получится шаблон .frx\r\n"
            "\r\n"
            "Из командной строки:\r\n"
            "  frx2docx.exe ПУТЬ --format both      шаблон -> Word и PDF\r\n"
            "  frx2docx.exe ПАПКА -r -o OUT         вся папка\r\n"
            "  frx2docx.exe ФАЙЛ --engine builtin   PDF без Word\r\n"
            "\r\n"
            "Подробности — README.ru.md рядом с этим файлом.\r\n"
            % __version__).encode("utf-8")


def main():
    os.makedirs(DIST, exist_ok=True)
    made = []
    print("Собираю портативный архив...")
    made.append(portable(os.path.join(
        DIST, "frx2docx-%s-portable.zip" % __version__)))
    print("Собираю архив с exe...")
    result = exe_only(os.path.join(DIST, "frx2docx-%s-exe.zip" % __version__))
    if result:
        made.append(result)
    print()
    for path in made:
        print("  %-40s %6.1f МБ" % (os.path.basename(path),
                                    os.path.getsize(path) / 1048576.0))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
