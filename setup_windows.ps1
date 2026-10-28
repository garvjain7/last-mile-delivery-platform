# Setup script for Windows PowerShell
# Creates Python virtual environment and installs all dependencies in one command.
# Needs Python 3.11 from python.org (the "py" launcher comes with it).
$ErrorActionPreference = "Stop"

Write-Host "Creating Python virtual environment (venv) with Python 3.11..." -ForegroundColor Green
py -3.11 -m venv venv
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 not found. Install it from https://www.python.org/downloads/ and run this again." }

Write-Host "Upgrading pip..." -ForegroundColor Green
.\venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "Installing all platform dependencies from requirements.txt..." -ForegroundColor Green
.\venv\Scripts\pip.exe install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing requirements failed (see the errors above)." }

Write-Host "Setup complete! Activate the environment with: .\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "Then, start the web services by running: honcho start -f Procfile.dev core_api control_tower gateway" -ForegroundColor Yellow
