@echo off
chcp 866 >nul
title Тесты frx2docx

set PY=%~dp0python\python.exe
if not exist "%PY%" set PY=python

echo.
echo   Гоняю тесты. Это занимает около минуты.
echo.
"%PY%" "%~dp0tests\test_frxkit.py"
echo.
pause
