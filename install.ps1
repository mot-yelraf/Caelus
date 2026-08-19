[CmdletBinding()]
param(
    [string]$InstallDir
)

$ErrorActionPreference = "Stop"
$SourceDir = $PSScriptRoot
$DefaultInstallDir = Join-Path $env:USERPROFILE "Caelus"
$InstallStateRoot = if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    Join-Path $env:USERPROFILE "AppData\Local"
} else {
    $env:LOCALAPPDATA
}
$InstallStateDir = Join-Path $InstallStateRoot "Caelus"
$InstallStateFile = Join-Path $InstallStateDir "install-location.txt"
$RememberedInstallDir = $DefaultInstallDir
if (Test-Path -LiteralPath $InstallStateFile -PathType Leaf) {
    $StoredInstallDir = (Get-Content -LiteralPath $InstallStateFile -Raw).Trim()
    if (-not [string]::IsNullOrWhiteSpace($StoredInstallDir)) {
        $RememberedInstallDir = $StoredInstallDir
    }
}

$ExplicitInstallDir = $PSBoundParameters.ContainsKey("InstallDir")
if (-not $ExplicitInstallDir -and -not [string]::IsNullOrWhiteSpace($env:CAELUS_INSTALL_DIR)) {
    $InstallDir = $env:CAELUS_INSTALL_DIR
    $ExplicitInstallDir = $true
}

if (-not $ExplicitInstallDir) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $InitialLocation = $RememberedInstallDir
    if (-not (Test-Path -LiteralPath $InitialLocation -PathType Container)) {
        $InitialLocation = Split-Path -Parent $RememberedInstallDir
    }
    if ([string]::IsNullOrWhiteSpace($InitialLocation) -or -not (Test-Path -LiteralPath $InitialLocation -PathType Container)) {
        $InitialLocation = $env:USERPROFILE
    }
    $LocationDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $LocationDialog.Description = "Choose the Caelus folder or a parent folder. If needed, a Caelus folder will be created."
    $LocationDialog.SelectedPath = $InitialLocation
    $LocationDialog.ShowNewFolderButton = $true
    if ($LocationDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Installation was cancelled."
    }
    $SelectedLocation = [System.IO.Path]::GetFullPath($LocationDialog.SelectedPath)
    if ([System.IO.Path]::GetFileName($SelectedLocation.TrimEnd([System.IO.Path]::DirectorySeparatorChar)) -ieq "Caelus") {
        $InstallDir = $SelectedLocation
    } else {
        $InstallDir = Join-Path $SelectedLocation "Caelus"
    }
    $LocationDialog.Dispose()
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    throw "InstallDir must name a dedicated application directory."
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
if ($InstallDir -eq [System.IO.Path]::GetPathRoot($InstallDir) -or
    $InstallDir -eq [System.IO.Path]::GetFullPath($env:USERPROFILE)) {
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
    foreach ($File in @("Caelus.py", "requirements.txt", "README.md", "install.sh", "install.ps1", "run_caelus.sh", "run_caelus_gui.sh", "run_caelus.ps1", "run_caelus_gui.ps1", "run_caelus.cmd", "run_caelus_gui.cmd")) {
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
& $VenvPython -c "import webview"
if ($LASTEXITCODE -ne 0) {
    throw "pywebview could not be imported after installation."
}

New-Item -ItemType Directory -Path $InstallStateDir -Force | Out-Null
$InstallStateTemp = "$InstallStateFile.tmp.$PID"
Set-Content -LiteralPath $InstallStateTemp -Value ([System.IO.Path]::GetFullPath($InstallDir)) -Encoding UTF8
Move-Item -LiteralPath $InstallStateTemp -Destination $InstallStateFile -Force

Write-Host ""
Write-Host "Caelus was installed in $InstallDir"
Write-Host "Start the desktop app with: $InstallDir\run_caelus_gui.cmd"
Write-Host "Start the headless server with: $InstallDir\run_caelus.cmd"
Write-Host "Open locally: http://127.0.0.1:8767"
Write-Host "Open on your LAN: http://<this-computer-LAN-IP>:8767"
Write-Host "Application data is preserved in: $InstallDir\data"
