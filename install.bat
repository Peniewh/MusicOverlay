@echo off
chcp 65001 >nul
setlocal

set APP_NAME=MusicOverlay
set INSTALL_DIR=%LOCALAPPDATA%\%APP_NAME%
set EXE_SRC=%~dp0dist\MusicOverlay.exe

if not exist "%EXE_SRC%" (
    echo Не найден %EXE_SRC%
    echo Сначала собери exe через build_exe.bat
    pause
    exit /b 1
)

echo === Установка в %INSTALL_DIR% ===
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /y "%EXE_SRC%" "%INSTALL_DIR%\%APP_NAME%.exe" >nul

echo === Ярлык на рабочем столе ===
set SCRIPT="%TEMP%\mklnk1.vbs"
> %SCRIPT% echo Set oWS = WScript.CreateObject("WScript.Shell")
>> %SCRIPT% echo sLinkFile = "%USERPROFILE%\Desktop\%APP_NAME%.lnk"
>> %SCRIPT% echo Set oLink = oWS.CreateShortcut(sLinkFile)
>> %SCRIPT% echo oLink.TargetPath = "%INSTALL_DIR%\%APP_NAME%.exe"
>> %SCRIPT% echo oLink.WorkingDirectory = "%INSTALL_DIR%"
>> %SCRIPT% echo oLink.Save
cscript //nologo %SCRIPT%
del %SCRIPT%

echo === Ярлык в меню Пуск ===
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs
set SCRIPT2="%TEMP%\mklnk2.vbs"
> %SCRIPT2% echo Set oWS = WScript.CreateObject("WScript.Shell")
>> %SCRIPT2% echo sLinkFile = "%STARTMENU%\%APP_NAME%.lnk"
>> %SCRIPT2% echo Set oLink = oWS.CreateShortcut(sLinkFile)
>> %SCRIPT2% echo oLink.TargetPath = "%INSTALL_DIR%\%APP_NAME%.exe"
>> %SCRIPT2% echo oLink.WorkingDirectory = "%INSTALL_DIR%"
>> %SCRIPT2% echo oLink.Save
cscript //nologo %SCRIPT2%
del %SCRIPT2%

echo.
echo === Установка завершена ===
echo Приложение: %INSTALL_DIR%\%APP_NAME%.exe
echo Ярлыки: рабочий стол и меню Пуск
echo.
pause