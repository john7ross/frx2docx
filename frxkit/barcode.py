# -*- coding: utf-8 -*-
"""Отрисовка штрихкодов в PNG без сторонних библиотек.

QR берётся из пакета qrcode, если он есть (он лежит в комплекте); всё
остальное — Code128, EAN-13/8, Code39, Interleaved 2 of 5 — считается здесь.
PNG собирается вручную через zlib, поэтому Pillow не нужен.
"""

from __future__ import annotations

import struct
import zlib


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------
def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_from_rows(rows, width, height):
    """rows — список строк по width байт (0 = чёрный, 255 = белый)."""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0,
                                          0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def png_from_matrix(matrix, box=4, border=4):
    """Квадратная матрица True/False -> PNG (для QR)."""
    n = len(matrix)
    side = (n + border * 2) * box
    blank = [255] * side
    rows = [list(blank) for _ in range(border * box)]
    for line in matrix:
        row = [255] * side
        for x, on in enumerate(line):
            if on:
                start = (x + border) * box
                for i in range(start, start + box):
                    row[i] = 0
        for _ in range(box):
            rows.append(list(row))
    rows.extend([list(blank) for _ in range(border * box)])
    return png_from_rows(rows, side, len(rows))


def png_from_bars(pattern, height=60, module=2, quiet=10, text=None):
    """pattern — строка из '0'/'1'; '1' = чёрная полоса."""
    width = (len(pattern) + quiet * 2) * module
    row = [255] * width
    for i, bit in enumerate(pattern):
        if bit == "1":
            start = (i + quiet) * module
            for x in range(start, start + module):
                row[x] = 0
    rows = [list(row) for _ in range(height)]
    if text:
        rows.extend([[255] * width for _ in range(module * 5)])
    return png_from_rows(rows, width, len(rows))


# --------------------------------------------------------------------------
# Code 128
# --------------------------------------------------------------------------
CODE128_PATTERNS = [
    "11011001100", "11001101100", "11001100110", "10010011000", "10010001100",
    "10001001100", "10011001000", "10011000100", "10001100100", "11001001000",
    "11001000100", "11000100100", "10110011100", "10011011100", "10011001110",
    "10111001100", "10011101100", "10011100110", "11001110010", "11001011100",
    "11001001110", "11011100100", "11001110100", "11101101110", "11101001100",
    "11100101100", "11100100110", "11101100100", "11100110100", "11100110010",
    "11011011000", "11011000110", "11000110110", "10100011000", "10001011000",
    "10001000110", "10110001000", "10001101000", "10001100010", "11010001000",
    "11000101000", "11000100010", "10110111000", "10110001110", "10001101110",
    "10111011000", "10111000110", "10001110110", "11101110110", "11010001110",
    "11000101110", "11011101000", "11011100010", "11011101110", "11101011000",
    "11101000110", "11100010110", "11101101000", "11101100010", "11100011010",
    "11101111010", "11001000010", "11110001010", "10100110000", "10100001100",
    "10010110000", "10010000110", "10000101100", "10000100110", "10110010000",
    "10110000100", "10011010000", "10011000010", "10000110100", "10000110010",
    "11000010010", "11001010000", "11110111010", "11000010100", "10001111010",
    "10100111100", "10010111100", "10010011110", "10111100100", "10011110100",
    "10011110010", "11110100100", "11110010100", "11110010010", "11011011110",
    "11011110110", "11110110110", "10101111000", "10100011110", "10001011110",
    "10111101000", "10111100010", "11110101000", "11110100010", "10111011110",
    "10111101110", "11101011110", "11110101110", "11010000100", "11010010000",
    "11010011100", "1100011101011",
]
START_B, START_C, STOP = 104, 105, 106


def code128(data):
    """Строка -> битовый рисунок. Автовыбор набора C для длинных цифр."""
    codes = []
    i = 0
    mode = None
    while i < len(data):
        run = 0
        while i + run < len(data) and data[i + run].isdigit():
            run += 1
        use_c = run >= (4 if mode == "C" else 6) or (i == 0 and run >= 4
                                                     and run == len(data))
        if use_c and run >= 2:
            if mode != "C":
                codes.append(START_C if mode is None else 99)
                mode = "C"
            take = run - (run % 2)
            for k in range(0, take, 2):
                codes.append(int(data[i + k:i + k + 2]))
            i += take
            continue
        if mode != "B":
            codes.append(START_B if mode is None else 100)
            mode = "B"
        ch = data[i]
        value = ord(ch) - 32
        codes.append(value if 0 <= value <= 94 else 0)
        i += 1
    if not codes:
        codes = [START_B]
    checksum = codes[0]
    for pos, value in enumerate(codes[1:], start=1):
        checksum += value * pos
    codes.append(checksum % 103)
    codes.append(STOP)
    return "".join(CODE128_PATTERNS[c] for c in codes)


# --------------------------------------------------------------------------
# EAN-13 / EAN-8 / UPC-A
# --------------------------------------------------------------------------
EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
         "0110001", "0101111", "0111011", "0110111", "0001011"]
EAN_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
         "0111001", "0000101", "0010001", "0001001", "0010111"]
EAN_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
         "1001110", "1010000", "1000100", "1001000", "1110100"]
EAN13_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
                "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def _ean_checksum(digits, even_weight=3):
    total = 0
    for i, d in enumerate(reversed(digits)):
        total += int(d) * (even_weight if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def ean13(data):
    digits = "".join(ch for ch in data if ch.isdigit())
    if len(digits) == 12:
        digits += str(_ean_checksum(digits))
    if len(digits) != 13:
        raise ValueError("EAN-13 ждёт 12 или 13 цифр, получено %d" % len(digits))
    parity = EAN13_PARITY[int(digits[0])]
    out = ["101"]
    for i, ch in enumerate(digits[1:7]):
        out.append(EAN_L[int(ch)] if parity[i] == "L" else EAN_G[int(ch)])
    out.append("01010")
    for ch in digits[7:]:
        out.append(EAN_R[int(ch)])
    out.append("101")
    return "".join(out)


def ean8(data):
    digits = "".join(ch for ch in data if ch.isdigit())
    if len(digits) == 7:
        digits += str(_ean_checksum(digits))
    if len(digits) != 8:
        raise ValueError("EAN-8 ждёт 7 или 8 цифр, получено %d" % len(digits))
    out = ["101"] + [EAN_L[int(c)] for c in digits[:4]] + ["01010"]
    out += [EAN_R[int(c)] for c in digits[4:]] + ["101"]
    return "".join(out)


# --------------------------------------------------------------------------
# Code 39
# --------------------------------------------------------------------------
CODE39 = {
    "0": "101001101101", "1": "110100101011", "2": "101100101011",
    "3": "110110010101", "4": "101001101011", "5": "110100110101",
    "6": "101100110101", "7": "101001011011", "8": "110100101101",
    "9": "101100101101", "A": "110101001011", "B": "101101001011",
    "C": "110110100101", "D": "101011001011", "E": "110101100101",
    "F": "101101100101", "G": "101010011011", "H": "110101001101",
    "I": "101101001101", "J": "101011001101", "K": "110101010011",
    "L": "101101010011", "M": "110110101001", "N": "101011010011",
    "O": "110101101001", "P": "101101101001", "Q": "101010110011",
    "R": "110101011001", "S": "101101011001", "T": "101011011001",
    "U": "110010101011", "V": "100110101011", "W": "110011010101",
    "X": "100101101011", "Y": "110010110101", "Z": "100110110101",
    "-": "100101011011", ".": "110010101101", " ": "100110101101",
    "$": "100100100101", "/": "100100101001", "+": "100101001001",
    "%": "101001001001", "*": "100101101101",
}


def code39(data):
    text = "*" + data.upper() + "*"
    parts = []
    for ch in text:
        parts.append(CODE39.get(ch, CODE39["-"]))
    return "0".join(parts)


# --------------------------------------------------------------------------
# Interleaved 2 of 5
# --------------------------------------------------------------------------
I25 = ["00110", "10001", "01001", "11000", "00101",
       "10100", "01100", "00011", "10010", "01010"]


def interleaved25(data):
    digits = "".join(ch for ch in data if ch.isdigit())
    if len(digits) % 2:
        digits = "0" + digits
    out = ["1010"]
    for i in range(0, len(digits), 2):
        a, b = I25[int(digits[i])], I25[int(digits[i + 1])]
        for k in range(5):
            out.append(("11" if a[k] == "1" else "1")
                       + ("00" if b[k] == "1" else "0"))
    out.append("11101")
    return "".join(out)


# --------------------------------------------------------------------------
# QR
# --------------------------------------------------------------------------
def qr_png(data, error_correction="L", box=4, border=4):
    """PNG QR-кода. None, если пакет qrcode недоступен."""
    try:
        import qrcode
        from qrcode.constants import (ERROR_CORRECT_L, ERROR_CORRECT_M,
                                      ERROR_CORRECT_Q, ERROR_CORRECT_H)
    except ImportError:
        return None
    levels = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M,
              "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    qr = qrcode.QRCode(error_correction=levels.get(error_correction,
                                                   ERROR_CORRECT_L),
                       border=0, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    return png_from_matrix(qr.get_matrix(), box=box, border=border)


# --------------------------------------------------------------------------
# точка входа
# --------------------------------------------------------------------------
LINEAR = {
    "code128": code128, "code128a": code128, "code128b": code128,
    "code128c": code128, "ean128": code128, "gs1128": code128,
    "code39": code39, "code39extended": code39,
    "ean13": ean13, "ean8": ean8, "upca": ean13,
    "2of5interleaved": interleaved25, "itf14": interleaved25,
}


def render(kind, data, height=60):
    """(kind, data) -> (png_bytes, квадратный ли) либо (None, причина)."""
    key = (kind or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    if not data:
        return None, "нет данных"
    if key in ("qrcode", "qr"):
        png = qr_png(data)
        if png is None:
            return None, "нет библиотеки qrcode"
        return png, True
    builder = LINEAR.get(key)
    if builder is None:
        return None, "тип %s не поддерживается" % kind
    try:
        pattern = builder(data)
    except ValueError as exc:
        return None, str(exc)
    return png_from_bars(pattern, height=height), False
