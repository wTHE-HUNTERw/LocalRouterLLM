@echo off
setlocal enabledelayedexpansion
title LocalRouterLLM - Asistente de Instalacion
cd /d "%~dp0"

echo =======================================================
echo     Iniciando Asistente de Instalacion Visual...
echo =======================================================
echo.

REM 1. Si existe el instalador compilado standalone (.exe), ejecutarlo directamente
if exist "%~dp0installer.exe" (
    start "" "%~dp0installer.exe"
    exit /b 0
)

REM 2. Fallback: Detectar interprete de Python para ejecutar installer.py
set "PYTHON_EXE="
if exist "C:\Users\%USERNAME%\miniconda3\pythonw.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\pythonw.exe"
) else if exist "C:\Users\%USERNAME%\miniconda3\python.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\python.exe"
) else if exist "%USERPROFILE%\miniconda3\pythonw.exe" (
    set "PYTHON_EXE=%USERPROFILE%\miniconda3\pythonw.exe"
) else if exist "%USERPROFILE%\miniconda3\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\miniconda3\python.exe"
) else (
    where pythonw >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PYTHON_EXE=pythonw"
    ) else (
        where python >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "PYTHON_EXE=python"
        )
    )
)

if "!PYTHON_EXE!"=="" (
    echo [ERROR] No se encontro Python ni installer.exe.
    echo Por favor instala Python 3.10+ o descarga installer.exe desde GitHub.
    pause
    exit /b 1
)

start "" "!PYTHON_EXE!" "%~dp0installer.py"
