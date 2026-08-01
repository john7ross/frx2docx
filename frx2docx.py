#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frx2docx — конвертер шаблонов FastReport в обе стороны.

    .frx                        ->  .docx / .pdf
    .docx / .md / .txt / .pdf   ->  .frx

Направление выбирается по расширению входного файла, отдельная команда
не нужна: перетащите на программу что угодно из перечисленного.

Запуск:
    python frx2docx.py template.frx
    python frx2docx.py template.frx --format both
    python frx2docx.py C:\\templates -r --format pdf -o OUT
    python frx2docx.py договор.docx

Подробности — в README.md, устройство — в ARCHITECTURE.md.
"""

from __future__ import annotations

import os
import sys


def _add_local_libs():
    """Зависимости, положенные рядом со скриптом (lib/ или vendor/),
    подключаются без установки в систему."""
    if getattr(sys, "frozen", False):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    for folder in ("lib", "vendor", "_deps"):
        path = os.path.join(here, folder)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


_add_local_libs()

try:
    import docx                                                # noqa: F401
except ImportError:                                            # pragma: no cover
    sys.exit("Не найден python-docx.\n"
             "Запустите УСТАНОВКА.bat из папки со скриптом,\n"
             "либо выполните:  pip install python-docx")

from frxkit.cli import main                                    # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
