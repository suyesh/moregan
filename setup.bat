@echo off
REM MoreGAN Quick Setup Script for Windows
REM Uses uv for fast Python dependency management

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║             MoreGAN Installer               ║
echo ╚══════════════════════════════════════════════╝
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python 3 is required but not installed.
    echo Please install Python 3.10 or higher from python.org
    pause
    exit /b 1
)

python -c "import sys; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Python 3.10 or higher is required.
    exit /b 1
)
python -c "from moregan import __version__; print('MoreGAN ' + __version__)"
echo ✓ Python detected

REM Check for uv
where uv >nul 2>&1
if errorlevel 1 (
    echo 📦 Installing uv (fast Python package manager)...
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

    REM Check if uv was installed
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ❌ Failed to install uv
        echo Please install manually from: https://github.com/astral-sh/uv
        pause
        exit /b 1
    )
)

echo ✓ uv is installed

REM Sync dependencies with uv
echo 📦 Syncing Python dependencies with uv...
uv sync --python python
if errorlevel 1 (
    echo ❌ Failed to sync dependencies with uv
    pause
    exit /b 1
)

REM Run the installer
echo 🚀 Launching MoreGAN installer...
echo.
uv run python install.py
if errorlevel 1 (
    echo ❌ Installer failed
    pause
    exit /b 1
)

echo.
echo ✨ Setup complete!
pause
