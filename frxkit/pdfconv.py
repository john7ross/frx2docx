# -*- coding: utf-8 -*-
"""Пересборка .docx в .pdf внешним движком: MS Word или LibreOffice.

Оба варианта работают пачкой — одна сессия конвертера на весь список файлов.
Если ни того, ни другого нет, вызывающий код переходит на встроенный
движок из pdfwrite.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

WORD_PS1 = """$ErrorActionPreference = 'Stop'
$list = Get-Content -LiteralPath $args[0] -Encoding UTF8
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try { $word.AutomationSecurity = 3 } catch { }
$ok = 0
try {
    foreach ($line in $list) {
        if (-not $line.Trim()) { continue }
        $pair = $line -split [regex]::Escape('|')
        try {
            if (Test-Path $pair[1]) { Remove-Item $pair[1] -Force }
            $doc = $word.Documents.Open($pair[0], $false, $true)
            $doc.ExportAsFixedFormat($pair[1], 17)
            $doc.Close(0)
            $ok = $ok + 1
        } catch {
            Write-Output ("FAIL|" + $pair[0] + "|" + $_.Exception.Message)
        }
    }
} finally {
    $word.Quit()
}
Write-Output ("DONE|" + $ok)
"""


def word_batch_powershell(pairs, timeout=900):
    """Одна сессия Word на всю пачку — через штатный COM в PowerShell.
    Не требует ни одной сторонней библиотеки."""
    if os.name != "nt":
        return {}, "Word доступен только в Windows"
    tmpdir = tempfile.mkdtemp(prefix="frx2docx_")
    listfile = os.path.join(tmpdir, "jobs.txt")
    ps1 = os.path.join(tmpdir, "word.ps1")
    try:
        with open(listfile, "w", encoding="utf-8") as fh:
            for src, dst in pairs:
                fh.write("%s|%s\n" % (os.path.abspath(src), os.path.abspath(dst)))
        with open(ps1, "w", encoding="utf-8-sig") as fh:
            fh.write(WORD_PS1)
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", ps1, listfile],
                capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            if isinstance(exc, FileNotFoundError):
                return {}, "PowerShell не найден"
            return ({}, "Word не ответил за %d с — вероятно, открыто окно с "
                        "диалогом (активация, восстановление файлов)" % timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        if "DONE|" not in out and not any(os.path.exists(d) for _, d in pairs):
            tail = [l for l in out.strip().splitlines() if l.strip()]
            return {}, ("PowerShell: " + (tail[-1][:160] if tail else
                                          "Word не запустился"))
        return {dst: os.path.exists(dst) for _, dst in pairs}, "MS Word (PowerShell)"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def word_batch_com(pairs):
    """То же самое, но через pywin32 / comtypes, если они доступны.
    Быстрее: без запуска PowerShell и без временных файлов."""
    if os.name != "nt":
        return {}, "Word доступен только в Windows"
    word = None
    engine_name = "pywin32"
    try:
        try:
            import win32com.client as com
            word = com.DispatchEx("Word.Application")
        except ImportError:
            import comtypes.client as ct
            engine_name = "comtypes"
            word = ct.CreateObject("Word.Application")
    except ImportError:
        return {}, "не установлены pywin32 / comtypes"
    except Exception as exc:                                  # noqa: BLE001
        return {}, "не удалось запустить Word: %s" % exc

    result = {}
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            word.AutomationSecurity = 3        # msoAutomationSecurityForceDisable
        except Exception:                                     # noqa: BLE001
            pass
        for src, dst in pairs:
            try:
                if os.path.exists(dst):
                    os.unlink(dst)
                doc = word.Documents.Open(os.path.abspath(src), False, True)
                doc.ExportAsFixedFormat(os.path.abspath(dst), 17)
                doc.Close(0)
                result[dst] = os.path.exists(dst)
            except Exception as exc:                          # noqa: BLE001
                result[dst] = False
                print("      Word не смог %s: %s" % (os.path.basename(src), exc))
    finally:
        try:
            word.Quit()
        except Exception:                                     # noqa: BLE001
            pass
    return result, "MS Word (%s)" % engine_name


def find_soffice():
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice", "/usr/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def soffice_batch(pairs, timeout=900):
    """LibreOffice умеет принимать список файлов за один запуск."""
    exe = find_soffice()
    if not exe:
        return {}, "LibreOffice (soffice) не найден"
    by_dir = {}
    for src, dst in pairs:
        by_dir.setdefault(os.path.dirname(os.path.abspath(dst)) or ".",
                          []).append((src, dst))
    result = {}
    for outdir, group in by_dir.items():
        cmd = [exe, "--headless", "--norestore", "--convert-to", "pdf",
               "--outdir", outdir] + [os.path.abspath(s) for s, _ in group]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            for _, dst in group:
                result[dst] = False
            continue
        for src, dst in group:
            produced = os.path.join(
                outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
            if (os.path.exists(produced)
                    and os.path.abspath(produced) != os.path.abspath(dst)):
                os.replace(produced, dst)
            result[dst] = os.path.exists(dst)
    return result, "LibreOffice"


def convert(pairs, engine="auto"):
    """Пачка (docx, pdf). Возвращает (что получилось, чем, ошибки)."""
    if not pairs:
        return {}, "", []
    chain = []
    if engine in ("auto", "word") and os.name == "nt":
        chain.append(word_batch_com)          # pywin32/comtypes — если есть
        chain.append(word_batch_powershell)   # иначе штатный COM
    if engine in ("auto", "libreoffice"):
        chain.append(soffice_batch)
    if engine == "word" and os.name != "nt":
        return {}, "", ["движок word доступен только в Windows"]

    done, errors, used = {}, [], ""
    remaining = list(pairs)
    for func in chain:
        if not remaining:
            break
        try:
            result, info = func(remaining)
        except Exception as exc:                              # noqa: BLE001
            errors.append("%s: %s" % (getattr(func, "__name__", "?"), exc))
            continue
        if not result:
            errors.append(info)
            continue
        used = used or info
        for dst, ok in result.items():
            if ok:
                done[dst] = info
        remaining = [(s, d) for s, d in remaining if not done.get(d)]
    return done, used, errors
