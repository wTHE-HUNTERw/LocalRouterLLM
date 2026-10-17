@echo off
setlocal enabledelayedexpansion
title LocalRouterLLM - Iniciando...
cd /d "%~dp0"

echo =======================================================
echo          Iniciando LocalRouterLLM v1.2.1
echo =======================================================

REM 1. Comprobar si ya esta ejecutandose y respondiendo en el puerto 8080
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 1; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] LocalRouterLLM ya esta activo y funcionando en segundo plano.
    echo [INFO] Abriendo panel de control en tu navegador...
    start http://127.0.0.1:8080/
    ping 127.0.0.1 -n 2 >nul 2>&1
    exit /b 0
)

REM 2. Seleccionar ejecutable (LocalRouterLLM.exe si existe, o Python)
if exist "%~dp0LocalRouterLLM.exe" (
    echo [1/2] Usando binario compilado: LocalRouterLLM.exe
    start "" "%~dp0LocalRouterLLM.exe"
) else (
    set "PYTHON_EXE="
    if exist "C:\Users\%USERNAME%\miniconda3\pythonw.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\pythonw.exe"
    ) else if exist "%USERPROFILE%\miniconda3\pythonw.exe" (
        set "PYTHON_EXE=%USERPROFILE%\miniconda3\pythonw.exe"
    ) else (
        where pythonw >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "PYTHON_EXE=pythonw"
        ) else (
            where python >nul 2>&1
            if !ERRORLEVEL! EQU 0 (
                set "PYTHON_EXE=python"
            ) else (
                echo [ERROR] No se encontro Python ni LocalRouterLLM.exe.
                echo Por favor ejecuta install.bat o instala Python 3.10+ / Miniconda.
                pause
                exit /b 1
            )
        )
    )
    echo [1/2] Usando interprete: !PYTHON_EXE!
    start "" "!PYTHON_EXE!" "%~dp0router.py"
)

echo [2/2] Esperando conexion con el servidor local...

REM 3. Esperar hasta 8 segundos verificando que el servidor responda
for /L %%i in (1,1,8) do (
    ping 127.0.0.1 -n 2 >nul 2>&1
    powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 1; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        goto :success
    )
)

:failed
echo.
echo =======================================================
echo [ADVERTENCIA] El router tardo mas de lo esperado en responder.
echo =======================================================
if exist "%~dp0router.log" (
    echo Ultimas lineas de router.log:
    powershell -NoProfile -Command "Get-Content '%~dp0router.log' -Tail 15"
)
echo.
echo Si el problema persiste, ejecuta start-debug.bat para ver los mensajes en vivo.
pause
exit /b 1

:success
echo.
echo =======================================================
echo           LocalRouterLLM Iniciado con Exito!
echo =======================================================
echo * Estado: En linea y listo
echo * Endpoint API: http://127.0.0.1:8080/v1
echo * Panel Web:    http://127.0.0.1:8080/
echo * Icono activo en la bandeja del sistema (System Tray).
echo =======================================================
ping 127.0.0.1 -n 3 >nul 2>&1
exit /b 0
