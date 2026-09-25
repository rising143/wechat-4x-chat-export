@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo   DbkeyHookCMD 密钥提取工具
echo ========================================
echo.

cd /d "%~dp0"

echo 正在以管理员权限运行 DbkeyHookCMD...
echo 参数: -pid 124316 -r
echo.

DbkeyHookCMD.exe -pid 124316 -r

echo.
echo ========================================
echo DbkeyHookCMD 已退出 (代码: %ERRORLEVEL%)
echo ========================================
pause
