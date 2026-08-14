[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE "Caelus")
)

$ErrorActionPreference = "Stop"
$SourceDir = $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($InstallDir) -or
    [System.IO.Path]::GetFullPath($InstallDir) -eq [System.IO.Path]::GetPathRoot($InstallDir) -or
    [System.IO.Path]::GetFullPath($InstallDir) -eq [System.IO.Path]::GetFullPath($env:USERPROFILE)) {
    throw "InstallDir must name a dedicated application directory."
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command py).Source
    $PythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command python).Source
    $PythonArgs = @()
} else {
    throw "Python 3.10 or newer was not found. Install Python from python.org and enable the Python launcher."
}

& $PythonExe @PythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}

$Directories = @(
    $InstallDir,
    (Join-Path $InstallDir "caelus"),
    (Join-Path $InstallDir "static"),
    (Join-Path $InstallDir "templates"),
    (Join-Path $InstallDir "data")
)
foreach ($Directory in $Directories) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}

if ([System.IO.Path]::GetFullPath($SourceDir) -ne [System.IO.Path]::GetFullPath($InstallDir)) {
    foreach ($File in @("Caelus.py", "requirements.txt", "README.md", "install.sh", "install.ps1", "run_caelus.sh", "run_caelus.ps1", "run_caelus.cmd")) {
        Copy-Item (Join-Path $SourceDir $File) (Join-Path $InstallDir $File) -Force
    }
    Copy-Item (Join-Path $SourceDir "caelus\*.py") (Join-Path $InstallDir "caelus") -Force
    Copy-Item (Join-Path $SourceDir "static\*") (Join-Path $InstallDir "static") -Recurse -Force
    Copy-Item (Join-Path $SourceDir "templates\*") (Join-Path $InstallDir "templates") -Recurse -Force
}

& $PythonExe @PythonArgs -m venv (Join-Path $InstallDir ".venv")
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the Caelus virtual environment."
}

$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed."
}

Write-Host ""
Write-Host "Caelus was installed in $InstallDir"
Write-Host "Start it with: $InstallDir\run_caelus.cmd"
Write-Host "Open locally: http://127.0.0.1:8767"
Write-Host "Open on your LAN: http://<this-computer-LAN-IP>:8767"
Write-Host "Application data is preserved in: $InstallDir\data"
