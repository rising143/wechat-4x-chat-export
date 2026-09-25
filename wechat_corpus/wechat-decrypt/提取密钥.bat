@echo off
chcp 65001 >nul 2>&1
title 微信密钥提取 - DbkeyHookCMD
echo ================================================================
echo.
echo   请在此窗口中观察输出
echo   微信将自动启动，请登录您的账号
echo   登录后工具会自动捕获密钥
echo.
echo ================================================================
echo.

cd /d "%~dp0"

DbkeyHookCMD.exe

echo.
echo ================================================================
echo   DbkeyHookCMD 已退出 (代码: %ERRORLEVEL%)
echo.
echo   如果上方显示了密钥(64位十六进制字符串)，请复制它
echo   例如: a1b2c3d4e5f6....
echo.
echo   检查微信目录是否有 dbkey.txt...
if exist "C:\personalsoftware\Weixin\dbkey.txt" (
    echo.
    echo   === 找到 dbkey.txt ===
    type "C:\personalsoftware\Weixin\dbkey.txt"
    echo.
    copy "C:\personalsoftware\Weixin\dbkey.txt" "%~dp0dbkey.txt" >nul 2>&1
    echo   已复制到脚本目录
)
echo.
echo   按任意键关闭
echo ================================================================
pause >nul
