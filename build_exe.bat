@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Готовлю иконку ===
if not exist "assets\miku.ico" (
    .venv\Scripts\python.exe make_ico.py
)

echo === Установка PyInstaller ===
.venv\Scripts\python.exe -m pip install pyinstaller

echo === Очистка прошлой сборки ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo === Сборка одного exe ===
.venv\Scripts\pyinstaller.exe ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name MusicOverlay ^
    --add-data "assets;assets" ^
    musicoverlay.py

echo.
echo === Готово ===
echo exe: dist\MusicOverlay.exe
echo.
echo Просто скопируй MusicOverlay.exe куда угодно — например на рабочий стол.
echo Первый запуск может занять 5-15 секунд (распаковка во временную папку).
pause