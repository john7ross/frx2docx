# -*- coding: utf-8 -*-
"""frxkit — конвертация шаблонов FastReport (.frx) в обе стороны.

Прямой путь:   .frx  -> .docx / .pdf
Обратный путь: .docx / .md / .txt / .pdf -> .frx

Модули:
    common     единицы измерения, разбор цветов, шрифтов, рамок, HTML-разметки
    rtf        RTF <-> размеченный текст (RichObject)
    barcode    QR / Code128 / EAN-13 без внешних библиотек
    frxread    чтение .frx в модель абсолютных прямоугольников
    layout     раскладка прямоугольников в табличную сетку
    docxwrite  сетка -> .docx
    pdfwrite   сетка -> .pdf (собственный движок)
    pdfimage   PNG / JPEG / BMP для движка PDF
    pdfconv    .docx -> .pdf через MS Word или LibreOffice
    fonts      метрики TrueType: перенос строк и встраивание в PDF
    doctree    промежуточная модель документа для обратного пути
    docxread   .docx -> doctree
    textread   .md / .txt -> doctree
    pdfparse   объекты, потоки и фильтры PDF
    pdfread    .pdf -> doctree
    frxwrite   doctree -> .frx
    cli        разбор командной строки и пакетная обработка
"""

__version__ = "2.0"
