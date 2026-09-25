@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo === Deep Key Search Start === > deep_search_log.txt
echo %date% %time% >> deep_search_log.txt
echo. >> deep_search_log.txt
where python >nul 2>&1 && (set "PY=python") || (set "PY=py -3")
%PY% deep_key_search.py >> deep_search_log.txt 2>&1
echo. >> deep_search_log.txt
echo === Exit Code: %ERRORLEVEL% === >> deep_search_log.txt
echo === Deep Key Search Done === >> deep_search_log.txt
