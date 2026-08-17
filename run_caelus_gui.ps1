$ErrorActionPreference = "Stop"
$RuntimeDir = $PSScriptRoot
$PythonExe = Join-Path $RuntimeDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe -PathType Leaf)) {
    throw "Caelus virtual environment is missing. Run $RuntimeDir\install.ps1 again."
}

Set-Location $RuntimeDir
& $PythonExe -m caelus.desktop @args
exit $LASTEXITCODE
