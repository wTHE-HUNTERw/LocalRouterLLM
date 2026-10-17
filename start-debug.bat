@echo off
title LocalRouterLLM (Modo Depuracion)
cd /d "%~dp0"
echo =======================================================
echo     Iniciando LocalRouterLLM en MODO DEPURACION
echo =======================================================
echo Esta ventana mostrara los registros y eventos en tiempo real.
echo Presiona Ctrl+C para detener el router.
echo =======================================================
echo.

if exist "%~dp0LocalRouterLLM.exe" (
    "%~dp0LocalRouterLLM.exe"
) else (
    python "%~dp0router.py"
)

echo.
echo =======================================================
echo El proceso ha finalizado.
echo =======================================================
pause
