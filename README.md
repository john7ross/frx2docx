# frx2docx

**English** · [Русский](README.ru.md)

Two-way converter between **FastReport templates (`.frx`)** and ordinary
documents. No installation, no external services, no cloud.

```
template.frx                  →  .docx  and/or  .pdf
document.docx / .pdf / .md / .txt  →  template.frx
```

Direction is chosen from the file extension — there is no subcommand to
remember. Drag files onto the program, or point it at a folder.

- **Language:** Python 3.9+ (ships with an embedded 3.14 runtime)
- **Hard dependency:** `python-docx` — that is all
- **PDF:** MS Word or LibreOffice when present, otherwise a **built-in
  pure-Python PDF engine** with real TrueType embedding and Cyrillic support
- **Platforms:** Windows (primary), Linux and macOS for everything except the
  Word COM path

## Why this exists

A FastReport template is XML full of absolutely-positioned objects. Lawyers,
managers and auditors cannot read it, and nobody wants to install the FastReport
designer just to review the wording of a contract. This tool turns a template
into a Word document that looks like the printed form, and turns an edited Word
document back into a template.

The reverse direction matters as much as the forward one: send the `.docx` to
legal, get their edits back, convert to `.frx`, open in the designer, keep the
`[root.Field]` placeholders intact the whole way.

## System requirements

| Item | Needed |
|---|---|
| OS | Windows 10 or 11, 64-bit. Linux and macOS for everything except the Word COM path |
| Disk | 60 MB unpacked, or 20 MB for the single `.exe` |
| Administrator rights | no |
| Internet | no — the program makes no network calls |
| Visual C++ Redistributable | no, the required runtime is part of Windows |
| Microsoft Word | **optional** — gives the most faithful PDF, but the built-in engine works without it |
| LibreOffice | **optional** — used when Word is absent |
| Fonts | nothing to install, fallbacks ship with the tool (see below) |

## Install

Nothing to install if you use the release archive: unpack it, the embedded
Python is inside. The single `frx2docx.exe` does not even need unpacking.

From source:

```bash
pip install -r requirements.txt
python frx2docx.py template.frx
```

`qrcode` and `pywin32` are optional — without them QR codes become a labelled
placeholder box and PDF goes through PowerShell COM or the built-in engine.

### The SmartScreen warning on first run

`frx2docx.exe` is not signed with a code-signing certificate — those are bought
from a certificate authority and cost money. So the first time you run a copy
downloaded from the internet, Windows shows a blue dialog:

> **Windows protected your PC**
> Microsoft Defender SmartScreen prevented an unrecognised app from starting.

This is **not** a virus detection. SmartScreen reacts this way to any unsigned
executable that has not yet built up a reputation. To continue, click **More
info**, then **Run anyway**.

If you want to check for yourself:

- upload the file to [virustotal.com](https://www.virustotal.com) and let a few
  dozen antivirus engines look at it;
- compare the checksum with the one on the release page:
  `Get-FileHash frx2docx.exe -Algorithm SHA256`;
- build the `.exe` yourself from source — the whole code is open;
- or just take the portable archive: it contains no `.exe` at all, only Python
  scripts, and SmartScreen does not trigger on it.

Copying the file over a local network or a shared folder produces no warning —
it only appears for files marked as downloaded from the internet.

## Fonts

The built-in PDF engine draws text with real TrueType outlines, so a font file
has to exist. The lookup order is:

1. **System fonts** — `C:\Windows\Fonts` and the per-user font folder. If the
   template asks for Arial and Arial is installed, Arial is what gets used.
2. **Bundled fallbacks** — the `fonts/` folder, also embedded in the `.exe`. It
   carries [Liberation](https://github.com/liberationfonts/liberation-fonts)
   (SIL Open Font License 1.1): Sans, Serif and Mono in all four styles.

Liberation was not an arbitrary choice: these faces are **metric-compatible**
with Arial, Times New Roman and Courier New — every character advance matches to
two decimal places, so substituting them does not move line breaks and the
layout stays put. They cover Cyrillic.

If a template asks for a font present neither in the system nor in the bundle,
the closest match by purpose is used (serif → Liberation Serif, sans →
Liberation Sans, monospace → Liberation Mono) and a warning naming the font is
printed. Your own fonts can simply be dropped into `fonts/`.

The `.frx → .docx` path does not read fonts at all: the font name is written
into the document and Word resolves it.

## Use

```bash
python frx2docx.py template.frx                 # → template.docx
python frx2docx.py template.frx --format both   # → .docx and .pdf
python frx2docx.py templates/ -r --format pdf -o OUT
python frx2docx.py contract.docx                # → contract.frx
python frx2docx.py scan.pdf                     # → scan.frx
python frx2docx.py notes.md                     # → notes.frx
```

| Flag | Meaning |
|---|---|
| `-f, --format docx\|pdf\|both\|frx` | output format (default: `docx` for `.frx`, `frx` for the rest) |
| `--pdf` | same as `--format both` |
| `--engine auto\|word\|libreoffice\|builtin` | which PDF engine to use; `auto` tries Word, then LibreOffice, then built-in |
| `-o, --outdir DIR` | where to write results (default: next to the source) |
| `-r, --recursive` | descend into subfolders |
| `--all-pages` | also convert `ReportPage` marked `Visible="false"` (skipped by default, matching FastReport print behaviour) |
| `-v, --verbose` | show every warning and full tracebacks |

For people who do not use a terminal, double-click **`КОНВЕРТИРОВАТЬ.bat`**:
it asks for the format, reads the `IN` folder and writes to `OUT`. Files can
also be dropped onto the `.bat` directly.

## What is carried across

### `.frx` → `.docx` / `.pdf`

| Carried | Notes |
|---|---|
| `TextObject` | font, size, weight, colour, alignment, padding, first-line indent, line height, word-wrap, 90°/270° rotation, hyperlinks |
| `TableObject` | column widths, row heights, `ColSpan`/`RowSpan`, per-side borders and widths, fill, nested objects inside cells |
| `RichObject` | RTF is parsed properly — bold, italic, underline, strikeout, size, colour, font and paragraph alignment survive |
| `PictureObject` | embedded base64, `ImageLocation` files, PNG/JPEG/BMP, `SizeMode` |
| `BarcodeObject` | QR, Code 128, EAN-13/8, Code 39, Interleaved 2 of 5 rendered for real when the content is a constant |
| `CheckBoxObject` | ☒ / ☐, including inside table cells |
| `LineObject`, `ShapeObject` | horizontal and vertical rules, rectangles with fill; other shapes approximate to a rectangle with a warning |
| `PageHeaderBand`, `PageFooterBand` | become real Word headers/footers, repeated on every page, with margins adjusted so the body keeps the same height as in FastReport |
| `[Page]`, `[TotalPages]` | become Word `PAGE` / `NUMPAGES` fields; substituted with real numbers in the built-in PDF engine |
| Page setup | paper size, orientation, margins, columns, watermark; each `ReportPage` becomes its own Word section |
| Inline `HtmlTags` markup | `<b> <i> <u> <s> <sub> <sup> <font face size color>` become real Word formatting |

### Not carried

- **`ScriptText`** — C# handlers (`BeforePrint` and friends) are not executed.
  What a script hides, shows or substitutes at print time is not reflected.
  Objects driven by a script are converted in their design-time state and the
  conversion log says so.
- **Data** — `[root.Field]` stays as text. This is a template converter, not a
  report generator.
- `SubreportObject`, `MSChartObject`, `MapObject`, gradient and hatch fills
  (approximated by their base colour), diagonal `LineObject`.

Every unsupported or approximated object produces a named warning, so nothing
disappears silently.

### `.docx` / `.pdf` / `.md` / `.txt` → `.frx`

| Source | What is read |
|---|---|
| `.docx` | sections and page setup, paragraphs with run formatting resolved through `styles.xml` (so heading styles survive), alignment, indents, spacing, tables with merges/borders/shading, inline images, headers and footers, `PAGE`/`NUMPAGES` fields → `[Page]`/`[TotalPages]` |
| `.pdf` | text with absolute coordinates, fonts, sizes, weight and colour; lines and frames; pieces are merged back into lines and paragraphs; page geometry and `/Rotate` |
| `.md` | headings, paragraphs, lists, pipe tables, rules, block quotes, `**bold**`, `*italic*`, `~~strike~~`, `` `code` `` |
| `.txt` | paragraphs separated by blank lines |

Output is a template that opens in the FastReport designer: `ReportPage` with
the right paper size and margins, `PageHeaderBand` / `DataBand` /
`PageFooterBand`, and `TextObject` / `TableObject` / `PictureObject` positioned
by measured text metrics.

## Checking the layout

```bash
python verify_layout.py templates/ OUT/
```

Compares, for every static caption, the distance from the left edge of the page
in the template and in the produced PDF. A healthy result is a median around
1 mm with an empty *tail* column. Needs no external tools — the PDF is parsed
by the same built-in parser.

Current result on the reference set of 11 production templates: median
**0.01–0.55 mm**, no captions beyond the 3 mm threshold.

## Tests

```bash
python tests/test_frxkit.py        # 53 tests, about a minute
```

Unit tests for the attribute parsers, RTF, barcodes, font metrics and
subsetting and the bundled fallbacks, the grid layout, the PDF lexer and
CMaps; end-to-end tests that
build `.docx` and `.pdf`, read them back and check round-trips both ways. Tests
that need system fonts or the local sample folder skip themselves.

## Building a distribution

- **Portable folder** — copy the whole directory. It carries its own Python.
- **Single file** — double-click `СОБРАТЬ EXE.bat` (needs the internet once, to
  fetch PyInstaller). Produces `dist/frx2docx.exe`, which needs nothing at all.

## A note on templates and secrets

A production `.frx` usually carries an `XmlDataConnection ConnectionString`
— an encrypted, but still sensitive, connection string — along with the full
list of data source fields. Keep real templates out of the repository; `IN/`
and `OUT/` are gitignored for exactly that reason. The only template in git is
`tests/data/features.frx`, which is synthetic and has no data source.

The converter itself sends nothing anywhere: no network calls, no telemetry.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — how it is built and why
- [CHANGELOG.md](CHANGELOG.md) — what changed

## Licence

MIT.
