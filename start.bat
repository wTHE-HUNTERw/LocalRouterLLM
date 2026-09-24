@echo off
title Iniciar LocalRouterLLM
cd /d "%~dp0"

REM Detectar pythonw
set PYW=pythonw
if exist "C:\Users\%USERNAME%\miniconda3\pythonw.exe" (
    set PYW=C:\Users\%USERNAME%\miniconda3\pythonw.exe
)

start "" "%PYW%" router.py

echo =======================================================
echo           LocalRouterLLM Iniciado!
echo =======================================================
echo El icono se encuentra activo en la bandeja del sistema (System Tray).
echo Listo para recibir peticiones en http://127.0.0.1:8080/v1
timeout /t 2 >nul
