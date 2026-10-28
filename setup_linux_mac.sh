#!/bin/bash
# Setup script for Linux/macOS
# Creates Python virtual environment and installs all dependencies in one command.
# Needs Python 3.11 (macOS ships 3.9 as python3): brew install python@3.11
set -e

PYTHON=${PYTHON:-$(command -v python3.11 || true)}
if [ -z "$PYTHON" ]; then
    echo "Python 3.11 not found. Install it (macOS: brew install python@3.11) or set PYTHON=/path/to/python3.11" >&2
    exit 1
fi

echo "Creating Python virtual environment (venv) with $($PYTHON --version)..."
"$PYTHON" -m venv venv

echo "Upgrading pip..."
./venv/bin/python -m pip install --upgrade pip

echo "Installing all platform dependencies from requirements.txt..."
./venv/bin/pip install -r requirements.txt

echo "Setup complete! Activate the environment with: source venv/bin/activate"
echo "Then, start the web services locally by running: honcho start -f Procfile.dev core_api control_tower gateway"
