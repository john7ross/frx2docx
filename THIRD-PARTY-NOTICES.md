# Third-party notices

frx2docx itself is MIT — see [LICENSE](LICENSE). It redistributes the
components below, each under its own licence.

## Liberation fonts

**What ships:** `fonts/LiberationSans-*.ttf`, `fonts/LiberationSerif-*.ttf`,
`fonts/LiberationMono-*.ttf` — twelve faces in total. They are also embedded
inside `frx2docx.exe`, so they travel with every distribution variant.

**Licence:** SIL Open Font License 1.1 — full text in
[`fonts/LICENSE-Liberation.txt`](fonts/LICENSE-Liberation.txt), authors in
[`fonts/AUTHORS-Liberation.txt`](fonts/AUTHORS-Liberation.txt).

**Copyright:** Digitized data copyright © 2010 Google Corporation with
Reserved Font Arimo, Tinos and Cousine. Copyright © 2012 Red Hat, Inc. with
Reserved Font Name Liberation.

**Source:** https://github.com/liberationfonts/liberation-fonts

**Modifications:** none. The files are shipped byte for byte as released
upstream (version 2.1.5), under their original names.

**Why they are here:** the built-in PDF engine draws text with real TrueType
outlines, so a font file has to exist on the machine. Liberation Sans, Serif
and Mono are metric-compatible with Arial, Times New Roman and Courier New —
substituting them does not move line breaks. See the *Fonts* section of the
[README](README.md).

## Runtime dependencies (not redistributed in source form)

The portable archive bundles a CPython runtime and these packages, each under
its own licence, with the licence text inside
`python/Lib/site-packages/*/`:

| Package | Licence |
|---|---|
| CPython | PSF License |
| python-docx | MIT |
| lxml | BSD-3-Clause |
| qrcode | BSD-3-Clause |
| pypng | MIT |
| pywin32 | PSF-style |

The single-file `frx2docx.exe` is built with PyInstaller (GPL with a
linking exception explicitly permitting proprietary and differently-licensed
bundled applications); PyInstaller itself is not part of the shipped program.
