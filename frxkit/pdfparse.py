# -*- coding: utf-8 -*-
"""Разбор PDF: объекты, страницы, шрифты, содержимое.

Ксреф не читаем принципиально: перебираем все вхождения «N G obj» по файлу
и разворачиваем потоки объектов (ObjStm). Так разбираются и битые файлы,
и линеаризованные, и PDF 1.5+ со сжатой таблицей ссылок.
"""

from __future__ import annotations

import re
import zlib

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"
OBJ_RE = re.compile(rb"(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b")


class Name(str):
    """Имя PDF (/Type) — отличаем от обычной строки."""
    __slots__ = ()


class Ref(object):
    __slots__ = ("num", "gen")

    def __init__(self, num, gen=0):
        self.num, self.gen = num, gen

    def __repr__(self):                                       # pragma: no cover
        return "Ref(%d)" % self.num

    def __eq__(self, other):
        return isinstance(other, Ref) and other.num == self.num

    def __hash__(self):
        return hash(("ref", self.num))


class Stream(object):
    __slots__ = ("dict", "raw", "_data")

    def __init__(self, d, raw):
        self.dict, self.raw, self._data = d, raw, None

    def data(self, doc=None):
        if self._data is None:
            self._data = decode_stream(self.dict, self.raw, doc)
        return self._data


# --------------------------------------------------------------------------
# лексер
# --------------------------------------------------------------------------
class Lexer(object):
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def skip(self):
        data, n = self.data, len(self.data)
        while self.pos < n:
            ch = data[self.pos]
            if ch in WHITESPACE:
                self.pos += 1
            elif ch == 0x25:                    # комментарий %
                while self.pos < n and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def token(self):
        self.skip()
        if self.pos >= len(self.data):
            return None
        ch = self.data[self.pos]
        if ch == 0x2F:                          # /Name
            return self._name()
        if ch == 0x28:                          # (строка)
            return self._literal()
        if ch == 0x3C:                          # << или <hex>
            if self.data[self.pos:self.pos + 2] == b"<<":
                self.pos += 2
                return "<<"
            return self._hex()
        if self.data[self.pos:self.pos + 2] == b">>":
            self.pos += 2
            return ">>"
        if ch in b"[]{}":
            self.pos += 1
            return chr(ch)
        return self._word()

    def _name(self):
        self.pos += 1
        start = self.pos
        data, n = self.data, len(self.data)
        while self.pos < n and data[self.pos] not in WHITESPACE \
                and data[self.pos] not in DELIMITERS:
            self.pos += 1
        raw = data[start:self.pos]
        if b"#" in raw:
            raw = re.sub(rb"#([0-9A-Fa-f]{2})",
                         lambda m: bytes([int(m.group(1), 16)]), raw)
        return Name(raw.decode("latin-1"))

    def _literal(self):
        self.pos += 1
        out = bytearray()
        depth = 1
        data, n = self.data, len(self.data)
        while self.pos < n:
            ch = data[self.pos]
            if ch == 0x5C:                      # обратная косая
                self.pos += 1
                if self.pos >= n:
                    break
                nxt = data[self.pos]
                mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
                if nxt in mapping:
                    out.append(mapping[nxt])
                    self.pos += 1
                elif 0x30 <= nxt <= 0x37:
                    digits = ""
                    while len(digits) < 3 and self.pos < n \
                            and 0x30 <= data[self.pos] <= 0x37:
                        digits += chr(data[self.pos])
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                elif nxt in b"\r\n":
                    self.pos += 1
                    if self.pos < n and data[self.pos - 1:self.pos + 1] == b"\r\n":
                        self.pos += 1
                else:
                    out.append(nxt)
                    self.pos += 1
                continue
            if ch == 0x28:
                depth += 1
            elif ch == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    break
            out.append(ch)
            self.pos += 1
        return bytes(out)

    def _hex(self):
        self.pos += 1
        start = self.pos
        end = self.data.find(b">", start)
        if end < 0:
            end = len(self.data)
        body = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[start:end])
        self.pos = end + 1
        if len(body) % 2:
            body += b"0"
        return bytes.fromhex(body.decode("ascii"))

    def _word(self):
        start = self.pos
        data, n = self.data, len(self.data)
        while self.pos < n and data[self.pos] not in WHITESPACE \
                and data[self.pos] not in DELIMITERS:
            self.pos += 1
        if self.pos == start:
            self.pos += 1
        return data[start:self.pos].decode("latin-1")


NUMBER_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


class Parser(Lexer):
    """Лексер + сборка составных объектов."""

    def value(self, token=None):
        tok = self.token() if token is None else token
        if tok is None:
            return None
        if isinstance(tok, (bytes, Name)):
            return tok
        if tok == "<<":
            return self._dict()
        if tok == "[":
            return self._array()
        if tok in ("]", ">>", "}", "{"):
            return None
        if NUMBER_RE.match(tok):
            save = self.pos
            second = self.token()
            if second is not None and isinstance(second, str) \
                    and NUMBER_RE.match(second) and "." not in tok:
                third = self.token()
                if third == "R":
                    return Ref(int(tok), int(float(second)))
            self.pos = save
            return float(tok) if "." in tok else int(tok)
        if tok == "true":
            return True
        if tok == "false":
            return False
        if tok == "null":
            return None
        return Name(tok)

    def _array(self):
        out = []
        while True:
            tok = self.token()
            if tok is None or tok == "]":
                return out
            out.append(self.value(tok))

    def _dict(self):
        out = {}
        while True:
            key = self.token()
            if key is None or key == ">>":
                break
            if not isinstance(key, Name):
                continue
            out[str(key)] = self.value()
        # поток?
        save = self.pos
        self.skip()
        if self.data[self.pos:self.pos + 6] == b"stream":
            self.pos += 6
            if self.data[self.pos:self.pos + 2] == b"\r\n":
                self.pos += 2
            elif self.data[self.pos:self.pos + 1] in (b"\n", b"\r"):
                self.pos += 1
            length = out.get("Length")
            start = self.pos
            if isinstance(length, int) and length >= 0 \
                    and self.data[start + length:start + length + 20].lstrip(
                        bytes(WHITESPACE)).startswith(b"endstream"):
                raw = self.data[start:start + length]
                self.pos = start + length
            else:
                end = self.data.find(b"endstream", start)
                raw = self.data[start:end if end > 0 else len(self.data)]
                raw = raw.rstrip(b"\r\n")
                self.pos = end if end > 0 else len(self.data)
            return Stream(out, raw)
        self.pos = save
        return out


# --------------------------------------------------------------------------
# фильтры
# --------------------------------------------------------------------------
def decode_stream(info, raw, doc=None):
    filters = info.get("Filter")
    if filters is None:
        return raw
    if not isinstance(filters, list):
        filters = [filters]
    params = info.get("DecodeParms") or info.get("DP")
    if not isinstance(params, list):
        params = [params] * len(filters)
    data = raw
    for name, parm in zip(filters, params):
        if doc is not None:
            parm = doc.resolve(parm)
        name = str(name)
        if name in ("FlateDecode", "Fl"):
            data = _inflate(data)
        elif name in ("LZWDecode", "LZW"):
            data = _lzw(data)
        elif name in ("ASCIIHexDecode", "AHx"):
            body = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            if len(body) % 2:
                body += b"0"
            data = bytes.fromhex(body.decode("ascii"))
        elif name in ("ASCII85Decode", "A85"):
            data = _a85(data)
        elif name in ("RunLengthDecode", "RL"):
            data = _runlength(data)
        else:
            return data                    # DCTDecode и прочие — как есть
        if isinstance(parm, dict) and parm.get("Predictor", 1) > 1:
            data = _unpredict(data, parm, doc)
    return data


def _inflate(data):
    try:
        return zlib.decompress(data)
    except zlib.error:
        try:
            return zlib.decompressobj().decompress(data)
        except zlib.error:
            try:
                return zlib.decompress(data, -15)
            except zlib.error:
                return b""


def _unpredict(data, parm, doc=None):
    predictor = int(parm.get("Predictor", 1))
    if predictor < 2:
        return data
    colors = int(parm.get("Colors", 1))
    bpc = int(parm.get("BitsPerComponent", 8))
    columns = int(parm.get("Columns", 1))
    bpp = max(1, colors * bpc // 8)
    stride = (columns * colors * bpc + 7) // 8
    if predictor == 2:
        return data
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    while pos + 1 <= len(data):
        ftype = data[pos]
        pos += 1
        line = bytearray(data[pos:pos + stride])
        if not line:
            break
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
        out += line
        prev = line
    return bytes(out)


def _a85(data):
    body = re.sub(rb"\s", b"", data)
    if body.startswith(b"<~"):
        body = body[2:]
    end = body.find(b"~>")
    if end >= 0:
        body = body[:end]
    out = bytearray()
    group = []
    for ch in body:
        if ch == 0x7A and not group:
            out += b"\x00\x00\x00\x00"
            continue
        group.append(ch - 33)
        if len(group) == 5:
            value = 0
            for g in group:
                value = value * 85 + g
            out += value.to_bytes(4, "big")
            group = []
    if group:
        pad = 5 - len(group)
        value = 0
        for g in group + [84] * pad:
            value = value * 85 + g
        out += value.to_bytes(4, "big")[:4 - pad]
    return bytes(out)


def _runlength(data):
    out = bytearray()
    i = 0
    while i < len(data):
        length = data[i]
        i += 1
        if length == 128:
            break
        if length < 128:
            out += data[i:i + length + 1]
            i += length + 1
        else:
            if i < len(data):
                out += bytes([data[i]]) * (257 - length)
            i += 1
    return bytes(out)


def _lzw(data, early=1):
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    bits, buffer, code_len = 0, 0, 9
    previous = None
    for byte in data:
        buffer = (buffer << 8) | byte
        bits += 8
        while bits >= code_len:
            code = (buffer >> (bits - code_len)) & ((1 << code_len) - 1)
            bits -= code_len
            if code == 256:
                table = [bytes([i]) for i in range(256)] + [b"", b""]
                code_len, previous = 9, None
                continue
            if code == 257:
                return bytes(out)
            if previous is None:
                entry = table[code]
            elif code < len(table):
                entry = table[code]
                table.append(previous + entry[:1])
            else:
                entry = previous + previous[:1]
                table.append(entry)
            out += entry
            previous = entry
            if len(table) + early >= (1 << code_len) and code_len < 12:
                code_len += 1
    return bytes(out)


# --------------------------------------------------------------------------
# документ
# --------------------------------------------------------------------------
class PdfDocument(object):
    def __init__(self, data):
        self.data = data
        self.objects = {}
        self._scan()
        self._expand_object_streams()

    def _scan(self):
        for m in OBJ_RE.finditer(self.data):
            num = int(m.group(1))
            parser = Parser(self.data, m.end())
            try:
                self.objects[num] = parser.value()
            except Exception:                                  # noqa: BLE001
                continue

    def _expand_object_streams(self):
        for obj in list(self.objects.values()):
            if not isinstance(obj, Stream):
                continue
            if str(obj.dict.get("Type", "")) != "ObjStm":
                continue
            try:
                body = obj.data(self)
                count = int(self.resolve(obj.dict.get("N", 0)))
                first = int(self.resolve(obj.dict.get("First", 0)))
            except Exception:                                  # noqa: BLE001
                continue
            head = body[:first].split()
            for i in range(count):
                try:
                    num = int(head[i * 2])
                    offset = int(head[i * 2 + 1])
                except (IndexError, ValueError):
                    break
                if num in self.objects:
                    continue
                try:
                    self.objects[num] = Parser(body, first + offset).value()
                except Exception:                              # noqa: BLE001
                    continue

    def resolve(self, value, depth=0):
        while isinstance(value, Ref) and depth < 32:
            value = self.objects.get(value.num)
            depth += 1
        return value

    def get(self, node, key, default=None):
        node = self.resolve(node)
        if not isinstance(node, dict):
            if isinstance(node, Stream):
                node = node.dict
            else:
                return default
        return self.resolve(node.get(key, default))

    # -- страницы ----------------------------------------------------------
    def catalog(self):
        for m in re.finditer(rb"/Root\s+(\d+)\s+(\d+)\s+R", self.data):
            node = self.resolve(Ref(int(m.group(1))))
            if isinstance(node, dict) and "Pages" in node:
                return node
        for obj in self.objects.values():
            if isinstance(obj, dict) and str(obj.get("Type", "")) == "Catalog":
                return obj
        return None

    def pages(self):
        root = self.catalog()
        result = []
        if root is not None:
            tree = self.resolve(root.get("Pages"))
            self._walk_pages(tree, {}, result, set())
        if not result:
            for num in sorted(self.objects):
                obj = self.objects[num]
                if isinstance(obj, dict) and str(obj.get("Type", "")) == "Page":
                    result.append(obj)
        return result

    INHERITED = ("Resources", "MediaBox", "CropBox", "Rotate")

    def _walk_pages(self, node, inherited, out, seen):
        node = self.resolve(node)
        if not isinstance(node, dict) or id(node) in seen:
            return
        seen.add(id(node))
        state = dict(inherited)
        for key in self.INHERITED:
            if key in node:
                state[key] = node[key]
        kind = str(node.get("Type", ""))
        kids = self.resolve(node.get("Kids"))
        if kind == "Pages" or (kids and kind != "Page"):
            for kid in kids or []:
                self._walk_pages(kid, state, out, seen)
            return
        page = dict(node)
        for key, value in state.items():
            page.setdefault(key, value)
        out.append(page)

    def content(self, page):
        chunks = []
        contents = self.resolve(page.get("Contents"))
        items = contents if isinstance(contents, list) else [contents]
        for item in items:
            stream = self.resolve(item)
            if isinstance(stream, Stream):
                chunks.append(stream.data(self))
        return b"\n".join(chunks)


def load(path):
    with open(path, "rb") as fh:
        return PdfDocument(fh.read())
