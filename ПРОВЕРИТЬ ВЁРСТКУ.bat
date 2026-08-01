@echo off
chcp 866 >nul
title Проверка вёрстки

set PY=%~dp0python\python.exe
if not exist "%PY%" set PY=python

echo.
echo   Сверяю положение надписей в готовых PDF с исходными шаблонами.
echo   Норма: медиана около 1 мм, столбец "хвост" нулевой.
echo.
"%PY%" "%~dp0verify_layout.py" "%~dp0IN" "%~dp0OUT"
echo.
pause
