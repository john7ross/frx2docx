# -*- coding: utf-8 -*-
"""Метрики TrueType: перенос строк и встраивание шрифта в PDF.

Читаем ровно те таблицы, которые нужны: head (единицы), hhea/hmtx (ширины),
cmap (символ -> глиф), OS/2 и post (флаги дескриптора). Сам файл шрифта
кладётся в PDF целиком как FontFile2 — этого достаточно и не требует
пересборки glyf, зато работает с любой кириллицей.
"""

from __future__ import annotations

import os
import struct
import sys

# семейства, которые почти всегда есть в Windows; ключ — как пишет FastReport
WINDOWS_FILES = {
    ("arial", 0): "arial.ttf", ("arial", 1): "arialbd.ttf",
    ("arial", 2): "ariali.ttf", ("arial", 3): "arialbi.ttf",
    ("times new roman", 0): "times.ttf", ("times new roman", 1): "timesbd.ttf",
    ("times new roman", 2): "timesi.ttf", ("times new roman", 3): "timesbi.ttf",
    ("courier new", 0): "cour.ttf", ("courier new", 1): "courbd.ttf",
    ("courier new", 2): "couri.ttf", ("courier new", 3): "courbi.ttf",
    ("tahoma", 0): "tahoma.ttf", ("tahoma", 1): "tahomabd.ttf",
    ("tahoma", 2): "tahoma.ttf", ("tahoma", 3): "tahomabd.ttf",
    ("verdana", 0): "verdana.ttf", ("verdana", 1): "verdanab.ttf",
    ("verdana", 2): "verdanai.ttf", ("verdana", 3): "verdanaz.ttf",
    ("calibri", 0): "calibri.ttf", ("calibri", 1): "calibrib.ttf",
    ("calibri", 2): "calibrii.ttf", ("calibri", 3): "calibriz.ttf",
    ("segoe ui", 0): "segoeui.ttf", ("segoe ui", 1): "segoeuib.ttf",
    ("segoe ui", 2): "segoeuii.ttf", ("segoe ui", 3): "segoeuiz.ttf",
    ("georgia", 0): "georgia.ttf", ("georgia", 1): "georgiab.ttf",
    ("georgia", 2): "georgiai.ttf", ("georgia", 3): "georgiaz.ttf",
    ("consolas", 0): "consola.ttf", ("consolas", 1): "consolab.ttf",
    ("consolas", 2): "consolai.ttf", ("consolas", 3): "consolaz.ttf",
}

# синонимы: одно и то же семейство под разными именами
SUBSTITUTES = {
    "helvetica": "arial", "sans-serif": "arial", "segoe": "segoe ui",
    "times": "times new roman", "serif": "times new roman",
    "courier": "courier new", "monospace": "courier new",
    "arimo": "liberation sans", "tinos": "liberation serif",
    "cousine": "liberation mono",
}

# Запасные шрифты, которые едут в комплекте. Liberation метрически совместимы
# с Arial, Times New Roman и Courier New, поэтому подмена не сдвигает переносы
# строк. Берутся, только если запрошенного семейства в системе нет.
BUNDLED_FALLBACK = {
    "arial": "liberation sans", "helvetica": "liberation sans",
    "sans-serif": "liberation sans", "segoe ui": "liberation sans",
    "calibri": "liberation sans", "tahoma": "liberation sans",
    "verdana": "liberation sans", "pt sans": "liberation sans",
    "times new roman": "liberation serif", "serif": "liberation serif",
    "cambria": "liberation serif", "georgia": "liberation serif",
    "garamond": "liberation serif", "pt astra serif": "liberation serif",
    "courier new": "liberation mono", "monospace": "liberation mono",
    "consolas": "liberation mono", "lucida console": "liberation mono",
}
DEFAULT_FALLBACK = "liberation sans"

LINUX_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts",
              os.path.expanduser("~/.fonts"))


def bundled_dir():
    """Папка fonts/ рядом с программой (или внутри собранного exe)."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "fonts")
    return path if os.path.isdir(path) else None


def _font_dirs():
    """Системные папки шрифтов, а последней — своя. Системный шрифт всегда
    выигрывает у запасного."""
    dirs = []
    if os.name == "nt":
        win = os.environ.get("SystemRoot", r"C:\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        dirs.extend(d for d in LINUX_DIRS if os.path.isdir(d))
        dirs.append("/Library/Fonts")
        dirs.append("/System/Library/Fonts")
    dirs = [d for d in dirs if os.path.isdir(d)]
    own = bundled_dir()
    if own:
        dirs.append(own)
    return dirs


_INDEX = None


def _system_index():
    """Имя семейства в нижнем регистре -> {стиль: путь}. Строится один раз."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    index = {}
    for folder in _font_dirs():
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith((".ttf", ".ttc", ".otf")):
                continue
            path = os.path.join(folder, name)
            try:
                info = probe(path)
            except Exception:                                  # noqa: BLE001
                continue
            if not info:
                continue
            family, style = info
            index.setdefault(family.lower(), {}).setdefault(style, path)
    _INDEX = index
    return index


def probe(path):
    """(семейство, стиль 0..3) из таблицы name, без полного разбора."""
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12:
            return None
        if head[:4] == b"ttcf":
            fh.seek(12)
            offset = struct.unpack(">I", fh.read(4))[0]
            fh.seek(offset)
            head = fh.read(12)
        num_tables = struct.unpack(">H", head[4:6])[0]
        base = fh.tell()
        tables = {}
        for i in range(num_tables):
            fh.seek(base + i * 16)
            rec = fh.read(16)
            if len(rec) < 16:
                break
            tag = rec[:4]
            off, length = struct.unpack(">II", rec[8:16])
            tables[tag] = (off, length)
        if b"name" not in tables:
            return None
        off, length = tables[b"name"]
        fh.seek(off)
        data = fh.read(length)
        family = _name_record(data, 1)
        sub = (_name_record(data, 2) or "").lower()
        style = 0
        if "bold" in sub:
            style |= 1
        if "italic" in sub or "oblique" in sub:
            style |= 2
        if b"OS/2" in tables:
            o, _ = tables[b"OS/2"]
            fh.seek(o + 62)
            raw = fh.read(2)
            if len(raw) == 2:
                fs = struct.unpack(">H", raw)[0]
                if fs & 0x20:
                    style |= 1
                if fs & 0x01:
                    style |= 2
        return (family or os.path.splitext(os.path.basename(path))[0], style)


def _name_record(data, name_id):
    if len(data) < 6:
        return None
    count, string_offset = struct.unpack(">HH", data[2:6])
    best = None
    for i in range(count):
        rec = data[6 + i * 12:18 + i * 12]
        if len(rec) < 12:
            break
        platform, encoding, _lang, nid, length, offset = struct.unpack(
            ">HHHHHH", rec)
        if nid != name_id:
            continue
        raw = data[string_offset + offset:string_offset + offset + length]
        try:
            if platform == 3 or (platform == 0):
                value = raw.decode("utf-16-be", errors="ignore")
            else:
                value = raw.decode("latin-1", errors="ignore")
        except Exception:                                      # noqa: BLE001
            continue
        value = value.strip("\x00").strip()
        if value and (best is None or platform == 3):
            best = value
    return best


def have(family):
    """Есть ли в системе именно это семейство (с учётом синонимов)."""
    name = (family or "").strip().lower()
    if not name:
        return True
    name = SUBSTITUTES.get(name, name)
    for folder in _font_dirs():
        if any(os.path.isfile(os.path.join(folder, WINDOWS_FILES[(name, s)]))
               for s in range(4) if (name, s) in WINDOWS_FILES):
            return True
    index = _system_index()
    if name in index:
        return True
    squashed = name.replace(" ", "")
    return any(key.replace(" ", "") == squashed for key in index)


def find_font_file(family, bold=False, italic=False):
    """Путь к файлу шрифта. None, если ничего похожего не нашлось."""
    style = (1 if bold else 0) | (2 if italic else 0)
    name = (family or "arial").strip().lower()
    name = SUBSTITUTES.get(name, name)

    for folder in _font_dirs():
        candidate = WINDOWS_FILES.get((name, style))
        if candidate:
            path = os.path.join(folder, candidate)
            if os.path.isfile(path):
                return path

    index = _system_index()
    faces = index.get(name)
    if faces is None:
        # PostScript-имена приходят без пробелов: TimesNewRoman, CourierNew
        squashed = name.replace(" ", "")
        for key in index:
            if key.replace(" ", "") == squashed:
                faces = index[key]
                break
    if faces is None:
        for key in index:
            if key.startswith(name) or name.startswith(key):
                faces = index[key]
                break
    if faces:
        return _pick(faces, style)

    # запрошенного семейства нет — берём метрически совместимую замену
    for fallback in (BUNDLED_FALLBACK.get(name), DEFAULT_FALLBACK,
                     "arial", "times new roman", "dejavu sans"):
        if not fallback:
            continue
        faces = index.get(fallback)
        if faces:
            return _pick(faces, style)
    for faces in index.values():                    # хоть что-нибудь
        return _pick(faces, style)
    return None


def _pick(faces, style):
    for want in (style, style & 1, style & 2, 0):
        if want in faces:
            return faces[want]
    return next(iter(faces.values()))


# --------------------------------------------------------------------------
# разбор шрифта
# --------------------------------------------------------------------------
class TrueTypeFont(object):
    """Минимальный разбор: ширины символов и данные для встраивания."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as fh:
            self.data = fh.read()
        self.offset = 0
        if self.data[:4] == b"ttcf":
            self.offset = struct.unpack(">I", self.data[12:16])[0]
            self.data = self.data                       # используем как есть
        self.tables = self._read_tables()
        self.is_cff = b"CFF " in self.tables and b"glyf" not in self.tables
        self._read_head()
        self._read_hmtx()
        self.cmap = self._read_cmap()
        self._read_descriptor()
        self._width_cache = {}

    # -- служебное ---------------------------------------------------------
    def _read_tables(self):
        base = self.offset
        num = struct.unpack(">H", self.data[base + 4:base + 6])[0]
        tables = {}
        for i in range(num):
            rec = self.data[base + 12 + i * 16:base + 28 + i * 16]
            if len(rec) < 16:
                break
            off, length = struct.unpack(">II", rec[8:16])
            tables[rec[:4]] = (off, length)
        return tables

    def _table(self, tag):
        entry = self.tables.get(tag)
        if not entry:
            return b""
        off, length = entry
        return self.data[off:off + length]

    def _read_head(self):
        head = self._table(b"head")
        self.units_per_em = struct.unpack(">H", head[18:20])[0] if head else 1000
        if not self.units_per_em:
            self.units_per_em = 1000
        self.bbox = struct.unpack(">hhhh", head[36:44]) if head else (0, 0, 0, 0)
        hhea = self._table(b"hhea")
        if hhea:
            self.ascent = struct.unpack(">h", hhea[4:6])[0]
            self.descent = struct.unpack(">h", hhea[6:8])[0]
            self.num_hmetrics = struct.unpack(">H", hhea[34:36])[0]
        else:
            self.ascent, self.descent, self.num_hmetrics = 800, -200, 1

    def _read_hmtx(self):
        hmtx = self._table(b"hmtx")
        self.advances = []
        for i in range(self.num_hmetrics):
            chunk = hmtx[i * 4:i * 4 + 2]
            if len(chunk) < 2:
                break
            self.advances.append(struct.unpack(">H", chunk)[0])
        if not self.advances:
            self.advances = [self.units_per_em // 2]

    def _read_cmap(self):
        data = self._table(b"cmap")
        if not data:
            return {}
        count = struct.unpack(">H", data[2:4])[0]
        best = None
        for i in range(count):
            rec = data[4 + i * 8:12 + i * 8]
            if len(rec) < 8:
                break
            platform, encoding, offset = struct.unpack(">HHI", rec)
            score = {(3, 10): 5, (3, 1): 4, (0, 4): 3, (0, 3): 3,
                     (0, 6): 3, (3, 0): 1}.get((platform, encoding), 0)
            if score and (best is None or score > best[0]):
                best = (score, offset)
        if best is None:
            return {}
        return self._read_subtable(data, best[1])

    def _read_subtable(self, data, offset):
        fmt = struct.unpack(">H", data[offset:offset + 2])[0]
        table = {}
        if fmt == 4:
            seg_x2 = struct.unpack(">H", data[offset + 6:offset + 8])[0]
            seg = seg_x2 // 2
            ends = struct.unpack(">%dH" % seg,
                                 data[offset + 14:offset + 14 + seg_x2])
            p = offset + 16 + seg_x2
            starts = struct.unpack(">%dH" % seg, data[p:p + seg_x2])
            p += seg_x2
            deltas = struct.unpack(">%dh" % seg, data[p:p + seg_x2])
            p += seg_x2
            range_offset_pos = p
            ranges = struct.unpack(">%dH" % seg, data[p:p + seg_x2])
            for i in range(seg):
                start, end = starts[i], ends[i]
                if start > end or end == 0xFFFF and start == 0xFFFF:
                    continue
                for code in range(start, min(end, 0xFFFE) + 1):
                    if ranges[i] == 0:
                        gid = (code + deltas[i]) & 0xFFFF
                    else:
                        pos = (range_offset_pos + i * 2 + ranges[i]
                               + (code - start) * 2)
                        if pos + 2 > len(data):
                            continue
                        gid = struct.unpack(">H", data[pos:pos + 2])[0]
                        if gid:
                            gid = (gid + deltas[i]) & 0xFFFF
                    if gid:
                        table[code] = gid
        elif fmt == 12:
            ngroups = struct.unpack(">I", data[offset + 12:offset + 16])[0]
            p = offset + 16
            for _ in range(min(ngroups, 20000)):
                start, end, gid = struct.unpack(">III", data[p:p + 12])
                p += 12
                for k in range(min(end - start, 0xFFFF) + 1):
                    table[start + k] = gid + k
        elif fmt == 6:
            first, count = struct.unpack(">HH", data[offset + 6:offset + 10])
            for i in range(count):
                gid = struct.unpack(
                    ">H", data[offset + 10 + i * 2:offset + 12 + i * 2])[0]
                if gid:
                    table[first + i] = gid
        return table

    def _read_descriptor(self):
        os2 = self._table(b"OS/2")
        post = self._table(b"post")
        self.italic_angle = 0.0
        if len(post) >= 12:
            raw = struct.unpack(">i", post[4:8])[0]
            self.italic_angle = raw / 65536.0
        self.cap_height = self.ascent
        self.stem_v = 80
        self.flags = 32                      # nonsymbolic
        if len(os2) >= 90:
            cap = struct.unpack(">h", os2[88:90])[0]
            if cap:
                self.cap_height = cap
        if len(os2) >= 32:
            weight = struct.unpack(">H", os2[4:6])[0]
            self.stem_v = max(50, int(weight / 5))
        if self.italic_angle:
            self.flags |= 64
        if len(os2) >= 64:
            fs = struct.unpack(">H", os2[62:64])[0]
            if fs & 0x20:
                self.flags |= 1 << 18        # ForceBold
        mono = self._table(b"post")
        if len(mono) >= 16 and struct.unpack(">I", mono[12:16])[0]:
            self.flags |= 1

    # -- открытая часть ----------------------------------------------------
    def gid(self, char):
        code = ord(char)
        g = self.cmap.get(code)
        if g is None and code == 0xA0:                # неразрывный пробел
            g = self.cmap.get(0x20)
        if g is None and code in (0x2011, 0x2010):    # дефисы
            g = self.cmap.get(0x2D)
        return g or 0

    def advance(self, gid):
        if gid < len(self.advances):
            return self.advances[gid]
        return self.advances[-1]

    def char_width(self, char):
        """Ширина символа в долях кегля."""
        w = self._width_cache.get(char)
        if w is None:
            w = self.advance(self.gid(char)) / float(self.units_per_em)
            self._width_cache[char] = w
        return w

    def text_width(self, text, size):
        return sum(self.char_width(ch) for ch in text) * size

    @property
    def line_height(self):
        return (self.ascent - self.descent) / float(self.units_per_em)


    # -- подмножество глифов ----------------------------------------------
    def _loca(self):
        head = self._table(b"head")
        if not head:
            return None
        long_format = struct.unpack(">h", head[50:52])[0]
        raw = self._table(b"loca")
        if not raw:
            return None
        if long_format:
            count = len(raw) // 4
            return list(struct.unpack(">%dI" % count, raw[:count * 4]))
        count = len(raw) // 2
        return [v * 2 for v in struct.unpack(">%dH" % count, raw[:count * 2])]

    def _components(self, glyf, loca, gid, seen):
        """Составной глиф тянет за собой части — собираем их рекурсивно."""
        if gid in seen or gid + 1 >= len(loca):
            return
        seen.add(gid)
        start, end = loca[gid], loca[gid + 1]
        if end <= start or end > len(glyf):
            return
        data = glyf[start:end]
        if len(data) < 10 or struct.unpack(">h", data[:2])[0] >= 0:
            return
        pos = 10
        while pos + 4 <= len(data):
            flags, index = struct.unpack(">HH", data[pos:pos + 4])
            pos += 4
            pos += 4 if flags & 1 else 2
            if flags & 8:
                pos += 2
            elif flags & 0x40:
                pos += 4
            elif flags & 0x80:
                pos += 8
            self._components(glyf, loca, index, seen)
            if not flags & 0x20:
                break

    def subset(self, gids):
        """Тот же шрифт, но с пустыми ненужными глифами. Нумерация глифов
        сохраняется — PDF ссылается на них напрямую (CIDToGIDMap /Identity)."""
        loca = self._loca()
        glyf = self._table(b"glyf")
        if loca is None or not glyf:
            return self.data
        keep = set()
        for gid in set(gids) | {0}:
            self._components(glyf, loca, gid, keep)
        keep = {g for g in keep if g + 1 < len(loca)}

        new_glyf = bytearray()
        new_loca = []
        for gid in range(len(loca) - 1):
            new_loca.append(len(new_glyf))
            if gid in keep:
                chunk = glyf[loca[gid]:loca[gid + 1]]
                new_glyf += chunk
                while len(new_glyf) % 4:
                    new_glyf.append(0)
        new_loca.append(len(new_glyf))

        head = bytearray(self._table(b"head"))
        struct.pack_into(">h", head, 50, 1)            # loca в длинном формате
        struct.pack_into(">I", head, 8, 0)             # checkSumAdjustment
        tables = {
            b"head": bytes(head),
            b"hhea": self._table(b"hhea"),
            b"maxp": self._table(b"maxp"),
            b"hmtx": self._table(b"hmtx"),
            b"loca": struct.pack(">%dI" % len(new_loca), *new_loca),
            b"glyf": bytes(new_glyf),
        }
        for tag in (b"cvt ", b"fpgm", b"prep", b"OS/2", b"post", b"gasp"):
            body = self._table(tag)
            if body:
                tables[tag] = body
        return _build_sfnt(tables)


def _build_sfnt(tables):
    tags = sorted(tables)
    count = len(tags)
    search = 1
    entry = 0
    while search * 2 <= count:
        search *= 2
        entry += 1
    out = bytearray(struct.pack(">IHHHH", 0x00010000, count, search * 16,
                                entry, count * 16 - search * 16))
    offset = 12 + count * 16
    directory = bytearray()
    body = bytearray()
    for tag in tags:
        data = tables[tag]
        padded = data + b"\x00" * (-len(data) % 4)
        directory += struct.pack(">4sIII", tag, _checksum(padded),
                                 offset + len(body), len(data))
        body += padded
    return bytes(out + directory + body)


def _checksum(data):
    total = 0
    for i in range(0, len(data), 4):
        total += struct.unpack(">I", data[i:i + 4])[0]
    return total & 0xFFFFFFFF


_CACHE = {}


def load(family, bold=False, italic=False):
    """Кэшированная загрузка. None, если шрифта в системе нет."""
    key = ((family or "").lower(), bool(bold), bool(italic))
    if key in _CACHE:
        return _CACHE[key]
    path = find_font_file(family, bold, italic)
    font = None
    if path:
        try:
            font = TrueTypeFont(path)
            if font.is_cff:                 # CFF в FontFile2 не встроить
                alt = find_font_file("arial", bold, italic)
                font = TrueTypeFont(alt) if alt else None
        except Exception:                                      # noqa: BLE001
            font = None
    _CACHE[key] = font
    return font


def measure(text, family, size, bold=False, italic=False):
    """Ширина строки в пунктах. Если шрифта нет — грубая оценка 0.5em."""
    font = load(family, bold, italic)
    if font is None:
        return len(text) * size * 0.5
    return font.text_width(text, size)


def wrap(text, family, size, max_width, bold=False, italic=False):
    """Перенос по словам под ширину max_width (в пунктах)."""
    font = load(family, bold, italic)
    if not text:
        return [""]
    if max_width <= 0:
        return [text]

    def width(s):
        return (font.text_width(s, size) if font
                else len(s) * size * 0.5)

    lines, current = [], ""
    for word in _split_words(text):
        candidate = current + word
        if current and width(candidate.rstrip()) > max_width:
            lines.append(current.rstrip())
            current = word.lstrip() if not word.strip() else word
        else:
            current = candidate
        while width(current.rstrip()) > max_width and len(current.strip()) > 1:
            cut = _break_long(current, width, max_width)
            if cut <= 0:
                break
            lines.append(current[:cut])
            current = current[cut:]
    lines.append(current.rstrip())
    return lines or [""]


def _split_words(text):
    """Слова вместе с идущими за ними пробелами."""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in " \t-\u2013\u2014/":
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _break_long(text, width, max_width):
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width(text[:mid]) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return lo
