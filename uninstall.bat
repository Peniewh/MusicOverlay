@echo off
chcp 65001 >nul
setlocal

set APP_NAME=MusicOverlay
set INSTALL_DIR=%LOCALAPPDATA%\%APP_NAME%

echo === Удаление %INSTALL_DIR% ===
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"

echo === Удаление ярлыков ===
if exist "%USERPROFILE%\Desktop\%APP_NAME%.lnk" del "%USERPROFILE%\Desktop\%APP_NAME%.lnk"
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\%APP_NAME%.lnk" del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\%APP_NAME%.lnk"

echo === Удаление из автозапуска ===
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /f >nul 2>nul

echo.
echo === Удаление завершено ===
pause