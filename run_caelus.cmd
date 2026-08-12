@echo off
setlocal
set "CAELUS_RUNTIME=%~dp0"
if not exist "%CAELUS_RUNTIME%.venv\Scripts\python.exe" (
  echo Caelus virtual environment is missing. Run install.ps1 again. 1>&2
  exit /b 1
)
cd /d "%CAELUS_RUNTIME%"
"%CAELUS_RUNTIME%.venv\Scripts\python.exe" "%CAELUS_RUNTIME%Caelus.py" %*
exit /b %ERRORLEVEL%
