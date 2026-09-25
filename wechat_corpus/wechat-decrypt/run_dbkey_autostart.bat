@echo off
chcp 65001 >nul 2>&1
set "EXEPATH=%~dp0DbkeyHookCMD.exe"
set "OUTFILE=%~dp0dbkey_output.txt"
:: 微信安装目录：如与实际不符，请修改此处或设置环境变量 WXDIR
if not defined WXDIR set "WXDIR=C:\personalsoftware\Weixin"

echo === DbkeyHookCMD Auto-Start Mode === > "%OUTFILE%"
echo Time: %date% %time% >> "%OUTFILE%"
echo Mode: Auto-start WeChat (no -r flag) >> "%OUTFILE%"
echo. >> "%OUTFILE%"

echo 正在启动 DbkeyHookCMD (自动启动微信模式)... >> "%OUTFILE%"
echo 请在微信启动后登录您的账号 >> "%OUTFILE%"
echo. >> "%OUTFILE%"
echo --- DbkeyHookCMD Output --- >> "%OUTFILE%"

"%EXEPATH%" >> "%OUTFILE%" 2>&1
set EC=%ERRORLEVEL%

echo. >> "%OUTFILE%"
echo --- End --- >> "%OUTFILE%"
echo ExitCode: %EC% >> "%OUTFILE%"
echo Time: %date% %time% >> "%OUTFILE%"

:: 检查微信目录是否有 dbkey.txt
if exist "%WXDIR%\dbkey.txt" (
    echo. >> "%OUTFILE%"
    echo === Found dbkey.txt in WeChat dir === >> "%OUTFILE%"
    type "%WXDIR%\dbkey.txt" >> "%OUTFILE%" 2>&1
)

:: 检查当前目录是否有 dbkey.txt
if exist "%CD%\dbkey.txt" (
    echo. >> "%OUTFILE%"
    echo === Found dbkey.txt in current dir === >> "%OUTFILE%"
    type "%CD%\dbkey.txt" >> "%OUTFILE%" 2>&1
)
