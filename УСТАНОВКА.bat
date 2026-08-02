@echo off
chcp 866 >nul
setlocal
title frx2docx - proverka i, esli nuzhno, ustanovka

set "HERE=%~dp0"
set "PY=%HERE%python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   Proveryayu, chego ne hvataet.
echo.

"%PY%" -c "import docx" 2>nul
if not errorlevel 1 (
    echo   Vsyo uzhe vnutri arhiva - stavit nechego.
    echo   Zapuskayte KONVERTIROVAT.bat
    echo.
    pause
    exit /b 0
)

echo   Bibliotek net - eto sborka iz ishodnikov. Stavlyu.
echo.

if exist "%HERE%wheels" (
    "%PY%" -m pip install --no-index --find-links "%HERE%wheels" python-docx qrcode pypng
) else (
    "%PY%" -m pip install -r "%HERE%requirements.txt"
)

if errorlevel 1 goto :fail
echo.
echo   Gotovo. Zapuskayte KONVERTIROVAT.bat
echo.
pause
exit /b 0

:fail
echo.
echo   Ne poluchilos. Proverte internet ili nalichie papki wheels.
echo.
pause
exit /b 1
