# Architecture

**English** · [Русский](ARCHITECTURE.ru.md)

`frx2docx` converts between an **absolutely-positioned** format (FastReport
`.frx`, and PDF) and **flow** formats (`.docx`, Markdown). Everything in the
design follows from that mismatch.

## The central idea

FastReport puts every object at fixed `Left/Top/Width/Height` coordinates. Word
flows paragraphs one after another. The common denominator that both can express
exactly is **a table with invisible borders**: columns come from the distinct
X coordinates of the objects in a band, rows from the Y coordinates, and each
object occupies a cell range with its own borders, fill and alignment.

That grid — produced by `layout.gridify()` — is the single intermediate form for
the forward direction. Both writers, `.docx` and `.pdf`, render the *same* grid,
so the two outputs agree by construction instead of by luck.

The reverse direction uses a different intermediate form, `doctree`, because the
input is already a document and the output has to be re-measured and re-placed.

```
                        forward
.frx ──frxread──► rects ──layout──► grid ──┬── docxwrite ──► .docx ──pdfconv──► .pdf
                                           └── pdfwrite  ──► .pdf   (built-in engine)

                        reverse
.docx ──docxread──┐
.pdf  ──pdfread ──┼──► doctree ──frxwrite──► .frx
.md   ──textread──┤
.txt  ────────────┘
```

## Technologies

| Concern | Choice | Why |
|---|---|---|
| Language | Python ≥ 3.9 | An embedded runtime ships with the tool; no install step for the user |
| `.docx` | `python-docx` + raw `lxml` for the parts it does not model | The only hard dependency |
| `.pdf` (write) | own writer over `zlib` | Removes the Word/LibreOffice requirement; Identity-H CID fonts give correct Cyrillic |
| `.pdf` (read) | own parser | No usable pure-Python PDF reader that is dependency-free; also lets `verify_layout` drop `poppler` |
| Fonts | own TrueType reader | Needed both for line breaking (forward) and for embedding + subsetting (PDF) |
| Fallback faces | Liberation (SIL OFL 1.1) | Metric-compatible with Arial / Times New Roman / Courier New, so substitution does not reflow the page |
| Barcodes | own encoders, `qrcode` optional | Code 128 / EAN / Code 39 / ITF are a few tables; QR is not |
| Images | own PNG/JPEG/BMP handling | Avoids Pillow |
| Tests | `unittest` | In the standard library, so the shipped runtime can run them |

## Modules

### Shared

- **`common.py`** — units (`1 unit = 1/96 in = 15 dxa = 0.75 pt`), colour, font,
  border and padding parsing *and* formatting, the `HtmlTags` subset both ways.
  Every other module speaks these units.
- **`fonts.py`** — locates TrueType files by family and style — system fonts
  first, then the bundled `fonts/` folder (inside the `.exe` when frozen) — reads
  `head`/`hhea`/`hmtx`/`cmap`/`OS/2`/`post`, measures strings, breaks lines, and
  builds a **glyph subset** for embedding. Subsetting keeps the original glyph
  numbering (empty `loca` entries for dropped glyphs) so the PDF can address
  glyphs directly through `CIDToGIDMap /Identity`. That one decision cut the
  generated PDFs from ~1.9 MB to ~150 KB.
  The bundle is Liberation Sans/Serif/Mono (SIL OFL 1.1), chosen because they
  are metric-compatible with Arial, Times New Roman and Courier New: an unknown
  family is replaced by the closest of the three and line breaks do not move.
  System fonts always win, so a template asking for Arial on a machine that has
  Arial gets the real thing.
- **`rtf.py`** — RTF in both directions, with the font and colour tables, group
  stack and `\uN` handling. Used by `RichObject` on the way out and available
  on the way back.
- **`barcode.py`** — Code 128 (auto set B/C), EAN-13/8, Code 39, Interleaved
  2 of 5, plus a hand-rolled PNG writer so no imaging library is needed.

### Forward path

- **`frxread.py`** — parses the XML (any declared encoding) into a flat list of
  rectangles. Each object type gets its own small function: `TextObject`,
  `TableObject` (with `ColSpan`/`RowSpan` and cells that omit covered columns),
  `RichObject`, `PictureObject`, `BarcodeObject`, `CheckBoxObject`,
  `LineObject`, `ShapeObject`. Bands are classified into body / header / footer;
  pages marked `Visible="false"` are skipped, matching what FastReport prints.
- **`layout.py`** — the grid builder. Also handles the two problems real
  templates always have: captions in the designer are wider than their text and
  overlap their neighbours (`clip_overlaps`), and some objects sit entirely on
  top of others (`extract_floats`, which lifts them into their own row). Large
  empty gaps become `spacer` blocks rather than empty table rows.
- **`docxwrite.py`** — grid → `.docx`. The non-obvious parts:
  - Empty cells carry a 1 pt paragraph mark, otherwise Word holds every row to
    the line height of the `Normal` style and the page slowly inflates.
  - `PageHeaderBand`/`PageFooterBand` become real headers/footers; the page
    margin is grown by exactly the band height and `header_distance` /
    `footer_distance` set to the original margin, so the body keeps the height
    FastReport gave it.
  - `[Page]` / `[TotalPages]` become `w:fldSimple` fields.
  - The watermark is a VML `v:rect` with a text box, not WordArt `v:textpath` —
    the latter is what Word's own UI writes but several Word builds decline to
    render it on export.
- **`pdfwrite.py`** — grid → `.pdf` directly. Text is laid out with the same
  font metrics used for measuring, justification places words individually
  (`Tw` does not work with two-byte Identity-H strings), rows that outgrow the
  page break at row boundaries, and a row taller than a whole page is split
  line by line so long paragraphs flow across pages. Two render passes: the
  first counts pages so `[TotalPages]` is known for the second.
- **`pdfconv.py`** — the external route: one Word session (pywin32/comtypes, or
  PowerShell COM as a fallback) or one LibreOffice invocation for the whole
  batch. Returns which files it managed, so the caller can fall back per file.

### Reverse path

- **`doctree.py`** — the document model: sections with page geometry, and
  blocks (`p`, `table`, `image`, `space`, `abs`). `abs` is the escape hatch for
  sources that already know their coordinates — that is, PDF.
- **`docxread.py`** — `.docx` → `doctree`. Walks the body in order so
  paragraphs and tables keep their sequence, resolves the `styles.xml` chain
  (`basedOn` + `docDefaults`) so styled headings are not lost, reconstructs
  `rowspan` from `vMerge`, and stays out of `w:pict` so watermarks are not read
  back as body text.
- **`pdfparse.py`** — the PDF object layer. It deliberately **does not read the
  cross-reference table**: it scans the file for every `N G obj` and expands
  object streams. That handles linearised files, PDF 1.5+ xref streams and
  damaged files with one code path. Filters: Flate, LZW, ASCIIHex, ASCII85,
  RunLength, plus PNG/TIFF predictors.
- **`pdfread.py`** — fonts (`ToUnicode` CMaps, `Encoding` + `Differences`,
  CID `W` arrays) and a content-stream interpreter that tracks the graphics and
  text matrices. Word emits a separate show-text operator per kerning pair, so
  the output is regrouped: glyph runs → lines → segments (split on real gaps,
  which is how columns survive) → paragraphs (consecutive single-segment lines
  with a common left edge, allowing the first line to be indented). Stroked
  paths and thin filled rectangles both become rules, and neighbouring pieces of
  the same border are merged back together.
- **`textread.py`** — Markdown and plain text.
- **`frxwrite.py`** — `doctree` → `.frx`. Measures every paragraph with
  `fonts.wrap` to decide its height, stacks blocks top to bottom, and emits
  `TextObject` / `TableObject` / `PictureObject` inside
  `PageHeaderBand` / `DataBand` / `PageFooterBand`. Mixed formatting inside a
  paragraph is written as `TextRenderType="HtmlTags"`.

### Entry points

- **`frx2docx.py`** — thin launcher: adds local library folders to `sys.path`,
  checks `python-docx`, calls `frxkit.cli.main`.
- **`frxkit/cli.py`** — argument parsing, input expansion, and the batching
  logic: all `.docx` are produced first, then PDFs are made in one external
  conversion run, and anything the external converter could not do falls back
  to the built-in engine per file.
- **`verify_layout.py`** — regression check for the layout; see below.

## Design decisions worth knowing

**Why not render the PDF from the `.docx`?** We do, when Word or LibreOffice is
available — their line breaking is the reference. The built-in engine exists so
the promise "no installation" holds on a machine with neither. Because both
renderers consume the same grid, the two outputs stay close: on the reference
set the built-in engine produces the same page count as Word for most templates,
and text positions match the template within 0.55 mm.

**Why scan for objects instead of reading the PDF xref?** Because the xref is
the part that is most often wrong, compressed into a stream, or duplicated by
incremental updates. Scanning costs one pass over the file and removes a whole
class of failures.

**Why keep glyph numbering when subsetting?** Renumbering would require a
`CIDToGIDMap` stream and rewriting every composite glyph reference. Keeping the
numbering and emptying unused `loca` slots is a few lines, keeps
`CIDToGIDMap /Identity`, and the leftover `loca` table costs a few kilobytes.

**Why are hidden pages skipped by default?** FastReport does not print a
`ReportPage` with `Visible="false"`. Templates use them for variants switched on
by script. Converting them all would be misleading; `--all-pages` is there when
you want to see them.

**Where the conversion is honest about its limits.** Script-driven state,
expression-driven barcodes, pictures substituted at print time and unsupported
object types each emit a named warning. The rule is that nothing disappears
without saying so.

## Verification

`verify_layout.py` is the layout regression test. It takes the template and the
produced PDF, and for every static left-aligned caption compares the distance
from the left edge of the page: expected from the FastReport coordinates,
actual from the glyph positions in the PDF. Captions that are centred, right
aligned, contain placeholders, or start with an indent are excluded because
there is nothing to compare them against.

On the reference set of 11 production templates the median offset is 0.01 mm
through Word and 0.53 mm through the built-in engine, with nothing beyond the
3 mm threshold.

`tests/test_frxkit.py` covers the rest: 53 tests over the parsers, RTF,
barcodes, font metrics and subsetting, the grid layout, the PDF lexer and
CMaps, and round-trips in both directions.

## Repository layout

```
frx2docx.py           entry point (both directions)
verify_layout.py      layout regression check
fonts/                bundled fallback faces + their licence
frxkit/               the package
  common.py           units, colours, fonts, borders, HtmlTags
  fonts.py            TrueType metrics, line breaking, subsetting
  rtf.py              RTF ↔ formatted runs
  barcode.py          Code128 / EAN / Code39 / ITF / QR + PNG writer
  frxread.py          .frx → rectangles
  layout.py           rectangles → grid
  docxwrite.py        grid → .docx
  pdfwrite.py         grid → .pdf (built-in engine)
  pdfimage.py         PNG/JPEG/BMP for the PDF engine
  pdfconv.py          .docx → .pdf via Word / LibreOffice
  doctree.py          document model for the reverse path
  docxread.py         .docx → doctree
  pdfparse.py         PDF objects, streams, filters
  pdfread.py          PDF fonts, content, grouping → doctree
  textread.py         Markdown / plain text → doctree
  frxwrite.py         doctree → .frx
  cli.py              command line and batching
tests/
  test_frxkit.py      53 tests
  data/               features.frx, contract.md
IN/ OUT/              working folders for the .bat launchers
python/               embedded runtime (not in git, ships in the release)
wheels/               offline wheels (not in git, ships in the release)
```
