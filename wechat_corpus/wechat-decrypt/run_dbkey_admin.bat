@echo off
chcp 65001 >nul 2>&1
set "EXEDIR=%~dp0"
set "OUTFILE=%EXEDIR%\dbkey_result.txt"

echo === DbkeyHookCMD Admin Run === > "%OUTFILE%"
echo Start: %date% %time% >> "%OUTFILE%"
echo WorkingDir: %EXEDIR% >> "%OUTFILE%"
echo. >> "%OUTFILE%"

cd /d "%EXEDIR%"

echo Running: DbkeyHookCMD.exe -pid 124316 -r >> "%OUTFILE%"
echo --- Output Start --- >> "%OUTFILE%"
DbkeyHookCMD.exe -pid 124316 -r >> "%OUTFILE%" 2>&1
echo --- Output End --- >> "%OUTFILE%"
echo ExitCode: %ERRORLEVEL% >> "%OUTFILE%"
echo End: %date% %time% >> "%OUTFILE%"
