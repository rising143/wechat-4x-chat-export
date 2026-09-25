@echo off
chcp 65001 >nul 2>&1
title DbkeyHookCMD 密钥提取工具
echo ================================================================
echo   DbkeyHookCMD 微信数据库密钥提取
echo ================================================================
echo.
echo 工作目录: %~dp0
echo.

cd /d "%~dp0"

echo [步骤1] 正在启动 DbkeyHookCMD (自动启动微信模式)...
echo        微信将自动启动，请在微信窗口中登录您的账号
echo        登录后工具会自动捕获数据库密钥
echo.
echo ----------------------------------------------------------------

DbkeyHookCMD.exe > dbkey_stdout.txt 2> dbkey_stderr.txt
echo.
echo ----------------------------------------------------------------
echo [完成] DbkeyHookCMD 退出码: %ERRORLEVEL%
echo.

echo [步骤2] 检查输出文件...
if exist dbkey_stdout.txt (
    echo === STDOUT 内容 ===
    type dbkey_stdout.txt
    echo.
)
if exist dbkey_stderr.txt (
    echo === STDERR 内容 ===
    type dbkey_stderr.txt
    echo.
)

echo [步骤3] 检查微信目录下的 dbkey.txt...
if exist "C:\personalsoftware\Weixin\dbkey.txt" (
    echo === 找到 dbkey.txt! ===
    type "C:\personalsoftware\Weixin\dbkey.txt"
    echo.
    copy "C:\personalsoftware\Weixin\dbkey.txt" dbkey.txt >nul
    echo 已复制到当前目录
) else (
    echo 未找到 C:\personalsoftware\Weixin\dbkey.txt
)

echo.
echo ================================================================
echo   请将以上输出截图或记下密钥内容
echo   按任意键关闭此窗口
echo ================================================================
pause >nul
