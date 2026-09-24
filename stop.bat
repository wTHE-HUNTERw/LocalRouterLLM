@echo off
title Detener LocalRouterLLM
cd /d "%~dp0"
echo =======================================================
echo Deteniendo LocalRouterLLM y liberando memoria...
echo =======================================================

REM Detener cualquier instancia de llama-server.exe
taskkill /F /IM llama-server.exe >nul 2>&1

REM Detener el proceso de python del router
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*LocalRouterLLM*router.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo.
echo [OK] LocalRouterLLM detenido y memoria VRAM/GPU liberada al 100%%.
echo =======================================================
timeout /t 3
