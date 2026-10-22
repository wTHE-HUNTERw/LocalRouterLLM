# =======================================================
# Asistente de Instalacion de LocalRouterLLM (PowerShell)
# =======================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Detectar Python
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
        Write-Error "Python no encontrado. Instala Python 3.10+ o Miniconda."
        exit 1
    }
}

# 2. Lanzar Asistente Visual de Instalacion
Write-Host "Iniciando Asistente Visual de Instalacion..." -ForegroundColor Cyan
Start-Process -FilePath $pythonExe -ArgumentList "`"$ScriptDir\installer.py`""
