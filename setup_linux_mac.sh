#!/bin/bash
# Setup script for Linux/macOS
# Creates Python virtual environment and installs all dependencies in one command.

echo "Creating Python virtual environment (venv)..."
python3 -m venv venv

echo "Upgrading pip..."
./venv/bin/python -m pip install --upgrade pip

echo "Installing all platform dependencies from requirements.txt..."
./venv/bin/pip install -r requirements.txt

echo "Setup complete! Activate the environment with: source venv/bin/activate"
echo "Then, start all services locally by running: honcho start -f Procfile.dev"
