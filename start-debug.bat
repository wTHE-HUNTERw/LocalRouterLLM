@echo off
title LocalRouterLLM (Modo Consola / Depuracion)
cd /d "%~dp0"
echo =======================================================
echo     Iniciando LocalRouterLLM en MODO CONSOLA
echo =======================================================
echo Esta ventana mostrara los registros y eventos en tiempo real.
echo Presiona Ctrl+C para detener el router.
echo =======================================================
echo.

set "PY_EXE=python"
if exist "C:\Users\%USERNAME%\miniconda3\python.exe" (
    set "PY_EXE=C:\Users\%USERNAME%\miniconda3\python.exe"
) else if exist "%USERPROFILE%\miniconda3\python.exe" (
    set "PY_EXE=%USERPROFILE%\miniconda3\python.exe"
)

"%PY_EXE%" "%~dp0router.py"

echo.
echo =======================================================
echo El proceso ha finalizado.
echo =======================================================
pause
