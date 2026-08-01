@echo off
chcp 866 >nul
setlocal
title Установка зависимостей frx2docx

set "HERE=%~dp0"
set "PY=%HERE%python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   Ставлю библиотеки, которые нужны конвертеру.
echo   Если рядом есть папка wheels - интернет не потребуется.
echo.

if exist "%HERE%wheels" (
    "%PY%" -m pip install --no-index --find-links "%HERE%wheels" python-docx qrcode pypng
) else (
    "%PY%" -m pip install -r "%HERE%requirements.txt"
)

if errorlevel 1 goto :fail
echo.
echo   Готово. Запускайте КОНВЕРТИРОВАТЬ.bat
echo.
pause
exit /b 0

:fail
echo.
echo   Не получилось. Проверьте интернет или наличие папки wheels.
echo.
pause
exit /b 1
