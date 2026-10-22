# =======================================================
# Asistente de Instalacion de LocalRouterLLM (PowerShell)
# =======================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Si existe installer.exe, lanzarlo directamente
$installerExe = "$ScriptDir\installer.exe"
if (Test-Path $installerExe) {
    Write-Host "Iniciando Asistente Visual de Instalacion (installer.exe)..." -ForegroundColor Cyan
    Start-Process -FilePath $installerExe
    exit 0
}

# 2. Fallback: Detectar Python
$pythonExe = "pythonw"
$condaPyw = "C:\Users\$env:USERNAME\miniconda3\pythonw.exe"
$condaPy = "C:\Users\$env:USERNAME\miniconda3\python.exe"

if (Test-Path $condaPyw) {
    $pythonExe = $condaPyw
} elseif (Test-Path $condaPy) {
    $pythonExe = $condaPy
} else {
    try {
        & python --version | Out-Null
        $pythonExe = "python"
    } catch {
        Write-Error "Python no encontrado. Instala Python 3.10+ o ejecuta installer.exe."
        exit 1
    }
}

# 3. Lanzar installer.py
Write-Host "Iniciando Asistente Visual de Instalacion (installer.py)..." -ForegroundColor Cyan
Start-Process -FilePath $pythonExe -ArgumentList "`"$ScriptDir\installer.py`""
