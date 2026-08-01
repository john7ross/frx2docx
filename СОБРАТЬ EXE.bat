@echo off
chcp 866 >nul
setlocal
title Сборка frx2docx.exe

rem %~dp0 заканчивается обратным слэшем, а он экранирует кавычку
rem в аргументах вида "...\" - поэтому слэш убираем.
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

set "PY=%HERE%\python\python.exe"
if not exist "%PY%" set "PY=python"

set "WORK=%TEMP%\frx2docx_build"

echo.
echo   Собираю один файл frx2docx.exe - ему не нужен ни Python,
echo   ни эта папка. Его можно просто отдать коллегам.
echo.
echo   Нужен интернет: скачается PyInstaller. Если интернета нет,
echo   пользуйтесь папкой целиком - она и так работает.
echo.
pause

"%PY%" -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 goto :fail

if exist "%HERE%\dist" rmdir /s /q "%HERE%\dist"
mkdir "%HERE%\dist"

"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --name frx2docx --collect-all docx --collect-all lxml --collect-all qrcode --collect-submodules frxkit --add-data "%HERE%onts;fonts" --hidden-import win32com.client --collect-all win32com --distpath "%HERE%\dist" --workpath "%WORK%" --specpath "%WORK%" "%HERE%\frx2docx.py"
if not errorlevel 1 goto :built
echo.
echo   Не собралось с поддержкой Word. Пробую без неё:
echo   exe будет делать PDF встроенным движком или через LibreOffice.
echo.
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --name frx2docx --collect-all docx --collect-all lxml --collect-all qrcode --collect-submodules frxkit --add-data "%HERE%onts;fonts" --distpath "%HERE%\dist" --workpath "%WORK%" --specpath "%WORK%" "%HERE%\frx2docx.py"
if errorlevel 1 goto :fail
:built

if not exist "%HERE%\dist\frx2docx.exe" goto :fail

echo.
echo   Готово: %HERE%\dist\frx2docx.exe
echo   Проверка версии:
"%HERE%\dist\frx2docx.exe" --version
echo.
echo   Как пользоваться: перетащите файлы на frx2docx.exe,
echo   либо из командной строки:
echo       frx2docx.exe ПУТЬ --format both
echo.
pause
exit /b 0

:fail
echo.
echo   Сборка не удалась. Папкой можно пользоваться и без exe:
echo   запускайте КОНВЕРТИРОВАТЬ.bat
echo.
pause
exit /b 1
