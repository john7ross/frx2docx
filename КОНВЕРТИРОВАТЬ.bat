@echo off
chcp 866 >nul
setlocal
title Конвертер шаблонов FastReport

set PY=%~dp0python\python.exe
if not exist "%PY%" set PY=python

echo.
echo   ======================================================
echo    Конвертер шаблонов FastReport
echo   ======================================================
echo.
echo   Шаблон .frx        -^> Word / PDF
echo   Word, PDF, MD, TXT -^> шаблон .frx
echo.

if not "%~1"=="" goto :dragdrop

if not exist "%~dp0IN" mkdir "%~dp0IN"
if not exist "%~dp0OUT" mkdir "%~dp0OUT"

dir /b "%~dp0IN\*.frx" "%~dp0IN\*.docx" "%~dp0IN\*.pdf" "%~dp0IN\*.md" "%~dp0IN\*.txt" >nul 2>nul
if errorlevel 1 (
    echo   В папке IN нет ни одного файла.
    echo   Положите туда .frx  ^(получите Word/PDF^)
    echo   или .docx / .pdf / .md / .txt  ^(получите шаблон .frx^).
    echo.
    start "" "%~dp0IN"
    pause
    exit /b 1
)

call :askformat
echo   Работаю. Если выбран PDF, запуск Word занимает время.
echo.
"%PY%" "%~dp0frx2docx.py" "%~dp0IN" -r --format %FMT% -o "%~dp0OUT"
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo   Готово. Открываю папку OUT с результатом.) else (echo   Часть файлов не обработалась - смотрите сообщения выше.)
start "" "%~dp0OUT"
echo.
pause
exit /b %RC%

:dragdrop
call :askformat
echo   Обрабатываю брошенные файлы...
echo.
:loop
if "%~1"=="" goto :done
"%PY%" "%~dp0frx2docx.py" "%~1" --format %FMT%
shift
goto :loop
:done
echo.
echo   Готово. Результат лежит рядом с исходными файлами.
echo.
pause
exit /b 0

:askformat
echo   В каком формате нужен результат для шаблонов .frx?
echo.
echo      [1]  Word  ^(.docx^)   - чтобы читать и править
echo      [2]  PDF   ^(.pdf^)    - чтобы отправить на согласование
echo      [3]  и Word, и PDF
echo.
echo   Для остальных файлов формат один - шаблон .frx.
echo.
choice /c 123 /n /m "   Нажмите 1, 2 или 3: "
if errorlevel 3 (set "FMT=both" & set "FMTNAME=Word и PDF") else if errorlevel 2 (set "FMT=pdf" & set "FMTNAME=PDF") else (set "FMT=docx" & set "FMTNAME=Word")
echo.
echo   Выбрано: %FMTNAME%
echo.
exit /b 0
