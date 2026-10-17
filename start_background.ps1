# LocalRouterLLM Silent Background Launcher
$routerDir = $PSScriptRoot
if (-not $routerDir) {
    $routerDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if (-not (Test-Path (Join-Path $routerDir "router.py"))) {
    $routerDir = "c:\Program Files\LlamaCPP\LocalRouterLLM"
}

$script = Join-Path $routerDir "router.py"
$pywCandidates = @(
    "C:\Users\$env:USERNAME\miniconda3\pythonw.exe",
    "$env:USERPROFILE\miniconda3\pythonw.exe"
)

$pyw = $null
foreach ($cand in $pywCandidates) {
    if (Test-Path $cand) {
        $pyw = $cand
        break
    }
}

if ($pyw) {
    Start-Process -FilePath $pyw -ArgumentList "`"$script`"" -WorkingDirectory $routerDir
} else {
    Start-Process -FilePath "pythonw" -ArgumentList "`"$script`"" -WorkingDirectory $routerDir
}
