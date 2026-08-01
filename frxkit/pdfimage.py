# -*- coding: utf-8 -*-
"""Подготовка растровых картинок к вставке в PDF без внешних библиотек.

JPEG уходит в PDF как есть (DCTDecode). PNG распаковывается целиком:
zlib + снятие фильтров строк, палитра разворачивается в RGB, альфа-канал
отбрасывается (PDF получил бы его отдельной маской, а прозрачность в
шаблонах встречается только у логотипов на белом).
"""

from __future__ import annotations

import struct
import zlib


def describe(blob):
    """-> dict(kind, width, height, colors, bpc, data, filter) либо None."""
    if blob[:2] == b"\xff\xd8":
        return _jpeg(blob)
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(blob)
    if blob[:2] == b"BM":
        return _bmp(blob)
    return None


# --------------------------------------------------------------------------
def _jpeg(blob):
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
            _, h, w, comps = struct.unpack(">BHHB", blob[i + 4:i + 10])
            return {"kind": "jpeg", "width": w, "height": h,
                    "colors": comps, "bpc": 8, "data": blob,
                    "filter": "/DCTDecode"}
        i += 2 + length
    return None


# --------------------------------------------------------------------------
def _png(blob):
    pos = 8
    idat = bytearray()
    palette = None
    width = height = 0
    bit_depth = color_type = interlace = 0
    while pos + 8 <= len(blob):
        length, tag = struct.unpack(">I4s", blob[pos:pos + 8])
        body = blob[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            (width, height, bit_depth, color_type, _comp, _filt,
             interlace) = struct.unpack(">IIBBBBB", body[:13])
        elif tag == b"PLTE":
            palette = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + length
    if not width or interlace:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    rows = _unfilter(raw, width, height, channels, bit_depth)
    if rows is None:
        return None

    if bit_depth < 8:
        rows = [_expand_bits(r, width, bit_depth) for r in rows]
        bit_depth = 8
    if bit_depth == 16:
        rows = [bytes(r[i] for i in range(0, len(r), 2)) for r in rows]
        bit_depth = 8

    if color_type == 3:
        if not palette:
            return None
        rows = [_apply_palette(r, palette, width) for r in rows]
        colors = 3
    elif color_type == 4:                                   # серый + альфа
        rows = [bytes(r[i] for i in range(0, len(r), 2)) for r in rows]
        colors = 1
    elif color_type == 6:                                   # RGBA
        rows = [_drop_alpha(r, 4, 3) for r in rows]
        colors = 3
    else:
        colors = channels

    data = zlib.compress(b"".join(rows), 9)
    return {"kind": "png", "width": width, "height": height,
            "colors": colors, "bpc": 8, "data": data,
            "filter": "/FlateDecode"}


def _unfilter(raw, width, height, channels, bit_depth):
    bpp = max(1, channels * bit_depth // 8)
    stride = (width * channels * bit_depth + 7) // 8
    out = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos >= len(raw):
            return None
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        if len(line) < stride:
            line.extend(b"\x00" * (stride - len(line)))
        pos += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif ftype != 0:
            return None
        out.append(bytes(line))
        prev = line
    return out


def _expand_bits(row, width, depth):
    out = bytearray()
    scale = 255 // ((1 << depth) - 1)
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    for i in range(width):
        byte = row[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        out.append(((byte >> shift) & mask) * scale)
    return bytes(out)


def _apply_palette(row, palette, width):
    out = bytearray()
    for i in range(width):
        idx = row[i] * 3
        out.extend(palette[idx:idx + 3] or b"\x00\x00\x00")
    return bytes(out)


def _drop_alpha(row, src_channels, keep):
    out = bytearray()
    for i in range(0, len(row), src_channels):
        out.extend(row[i:i + keep])
    return bytes(out)


# --------------------------------------------------------------------------
def _bmp(blob):
    if len(blob) < 54:
        return None
    offset = struct.unpack("<I", blob[10:14])[0]
    width, height = struct.unpack("<ii", blob[18:26])
    planes, bpp = struct.unpack("<HH", blob[26:30])
    compression = struct.unpack("<I", blob[30:34])[0]
    if planes != 1 or compression != 0 or bpp not in (24, 32):
        return None
    flip = height > 0
    height = abs(height)
    stride = ((width * bpp // 8) + 3) & ~3
    rows = []
    for y in range(height):
        start = offset + y * stride
        line = blob[start:start + width * (bpp // 8)]
        pix = bytearray()
        step = bpp // 8
        for x in range(0, len(line), step):
            b, g, r = line[x], line[x + 1], line[x + 2]
            pix.extend((r, g, b))
        rows.append(bytes(pix))
    if flip:
        rows.reverse()
    return {"kind": "bmp", "width": width, "height": height,
            "colors": 3, "bpc": 8, "data": zlib.compress(b"".join(rows), 9),
            "filter": "/FlateDecode"}
