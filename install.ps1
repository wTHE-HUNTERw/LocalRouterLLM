# =======================================================
# Instalador de LocalRouterLLM para PowerShell
# =======================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "          Instalador de LocalRouterLLM" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detectar Python
$pythonExe = "python"
try {
    & python --version | Out-Null
} catch {
    $condaPy = "C:\Users\$env:USERNAME\miniconda3\python.exe"
    if (Test-Path $condaPy) {
        $pythonExe = $condaPy
    } else {
        Write-Error "Python no encontrado. Instala Python 3.10+ o Miniconda."
        exit 1
    }
}

Write-Host "[1/3] Usando Python: $pythonExe" -ForegroundColor Green

# 2. Instalar dependencias
Write-Host "[2/3] Instalando dependencias de Python..." -ForegroundColor Yellow
& $pythonExe -m pip install -r "$ScriptDir\requirements.txt" | Out-Null
Write-Host "[OK] Dependencias instaladas (pystray, Pillow)." -ForegroundColor Green

# 3. Configuración
Write-Host "[3/3] Comprobando configuracion..." -ForegroundColor Yellow
$cfg = "$ScriptDir\config.json"
$exampleCfg = "$ScriptDir\config.example.json"
if (-not (Test-Path $cfg)) {
    Copy-Item $exampleCfg $cfg
    Write-Host "[OK] Creado config.json desde plantilla." -ForegroundColor Green
} else {
    Write-Host "[OK] config.json ya existe." -ForegroundColor Green
}

# 4. Integración opcional con PowerShell Profile
Write-Host ""
$choice = Read-Host "¿Deseas instalar el hook automático en tu PowerShell Profile para OpenCode? (S/N)"
if ($choice -eq "S" -or $choice -eq "s") {
    $profilePath = $PROFILE
    $profileDir = Split-Path $profilePath
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }

    $hookCode = @"

# =========================================================
# LocalRouterLLM + OpenCode Auto-Hook
# =========================================================
function opencode {
    `$routerActive = `$false
    try {
        `$tcp = New-Object System.Net.Sockets.TcpClient
        `$connect = `$tcp.BeginConnect("127.0.0.1", 8080, `$null, `$null)
        if (`$connect.AsyncWaitHandle.WaitOne(150, `$false) -and `$tcp.Connected) {
            `$routerActive = `$true
            `$tcp.EndConnect(`$connect)
        }
        `$tcp.Close()
    } catch {}

    if (-not `$routerActive) {
        Write-Host "[LocalRouterLLM] Iniciando router inteligente en segundo plano..." -ForegroundColor Cyan
        `$pyw = "$pythonExe" -replace "python\.exe", "pythonw.exe"
        if (-not (Test-Path `$pyw)) { `$pyw = "pythonw" }
        Start-Process -FilePath `$pyw -ArgumentList "`"$ScriptDir\router.py`""
        Start-Sleep -Milliseconds 300
    }

    `$opencodeExe = "`$env:APPDATA\npm\node_modules\opencode-ai\bin\opencode.exe"
    if (Test-Path `$opencodeExe) {
        & `$opencodeExe @args
    } else {
        & "`$env:APPDATA\npm\opencode.ps1" @args
    }
}
"@

    Add-Content -Path $profilePath -Value $hookCode -Encoding UTF8
    Write-Host "[OK] Hook añadido a tu perfil de PowerShell: $profilePath" -ForegroundColor Green
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "       LocalRouterLLM Listo para Usarse!" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "Ejecuta start.bat para iniciarlo manualmente." -ForegroundColor White
