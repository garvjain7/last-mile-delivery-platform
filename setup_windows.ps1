# Setup script for Windows PowerShell
# Creates Python virtual environment and installs all dependencies in one command.

Write-Host "Creating Python virtual environment (venv)..." -ForegroundColor Green
python -m venv venv

Write-Host "Upgrading pip..." -ForegroundColor Green
.\venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "Installing all platform dependencies from requirements.txt..." -ForegroundColor Green
.\venv\Scripts\pip.exe install -r requirements.txt

Write-Host "Setup complete! Activate the environment with: .\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
