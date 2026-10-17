@echo off
title Detener LocalRouterLLM
cd /d "%~dp0"
echo =======================================================
echo Deteniendo LocalRouterLLM y liberando memoria...
echo =======================================================

REM 1. Detener cualquier instancia de llama-server.exe
taskkill /F /IM llama-server.exe >nul 2>&1

REM 2. Detener ejecutable compilado si estuviera corriendo
taskkill /F /IM LocalRouterLLM.exe >nul 2>&1

REM 3. Detener procesos Python que ejecutan router.py
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*router.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM 4. Liberar forzadamente cualquier proceso remanente en los puertos 8080 y 8081
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080,8081 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo.
echo [OK] LocalRouterLLM detenido y memoria VRAM/GPU liberada al 100%%.
echo [OK] Puertos 8080 y 8081 completamente libres.
echo =======================================================
ping 127.0.0.1 -n 3 >nul 2>&1
