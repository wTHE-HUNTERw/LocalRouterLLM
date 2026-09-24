@echo off
title Instalador de LocalRouterLLM
cd /d "%~dp0"
echo =======================================================
echo          Instalador de LocalRouterLLM
echo =======================================================
echo.

REM Detectar Python
set PYTHON_CMD=python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "C:\Users\%USERNAME%\miniconda3\python.exe" (
        set PYTHON_CMD=C:\Users\%USERNAME%\miniconda3\python.exe
    ) else (
        echo [ERROR] No se encontro Python en el sistema.
        echo Por favor instala Python 3.10+ o Miniconda para continuar.
        pause
        exit /b 1
    )
)

echo [1/3] Usando Python: %PYTHON_CMD%
echo.

echo [2/3] Instalando dependencias de Python (pystray, Pillow)...
"%PYTHON_CMD%" -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ADVERTENCIA] Fallo al instalar via requirements.txt, intentando directo...
    "%PYTHON_CMD%" -m pip install pystray Pillow
)

echo.
echo [3/3] Comprobando archivo de configuracion...
if not exist "config.json" (
    copy "config.example.json" "config.json" >nul
    echo [OK] Archivo config.json generado a partir de la plantilla.
) else (
    echo [OK] config.json ya existe.
)

echo.
echo =======================================================
echo       LocalRouterLLM Instalado con Exito!
echo =======================================================
echo.
echo Puedes iniciarlo en cualquier momento ejecutando start.bat
echo o configurando el hook en tu terminal.
echo.
pause
