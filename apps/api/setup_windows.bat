@echo off
echo Setting up Python virtual environment for Windows...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    exit /b 1
)

cd /d "%~dp0"

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Setup complete!
echo.
echo To start the API server, run:
echo   venv\Scripts\activate.bat
echo   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
