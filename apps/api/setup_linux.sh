#!/bin/bash
set -e

echo "Setting up Python virtual environment for Linux/WSL..."

if ! command -v python3 &> /dev/null; then
    echo "Python3 is not installed"
    exit 1
fi

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv || {
        echo "Failed to create venv. Installing python3-venv..."
        sudo apt update && sudo apt install -y python3-venv
        python3 -m venv venv
    }
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo ""
echo "To start the API server, run:"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
