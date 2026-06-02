#!/usr/bin/env bash

# hooliGAN-harness Quick Setup Script
# Uses uv for fast Python dependency management

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Banner
echo -e "${MAGENTA}${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║        hooliGAN-harness Installer           ║"
echo "║              Version 1.5.0                  ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is required but not installed.${NC}"
    echo -e "${YELLOW}Please install Python 3.8 or higher.${NC}"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED_VERSION="3.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}❌ Python $REQUIRED_VERSION or higher is required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION detected"

# Check for uv and install if needed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}📦 Installing uv (fast Python package manager)...${NC}"

    # Detect OS
    OS="$(uname -s)"
    case "${OS}" in
        Linux*)
            curl -LsSf https://astral.sh/uv/install.sh | sh
            ;;
        Darwin*)
            # macOS - try brew first, then curl
            if command -v brew &> /dev/null; then
                brew install uv
            else
                curl -LsSf https://astral.sh/uv/install.sh | sh
            fi
            ;;
        MINGW*|CYGWIN*|MSYS*)
            # Windows
            powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
            ;;
        *)
            echo -e "${RED}Unsupported OS: ${OS}${NC}"
            echo -e "${YELLOW}Please install uv manually: https://github.com/astral-sh/uv${NC}"
            exit 1
            ;;
    esac

    # Add to PATH if needed
    export PATH="$HOME/.cargo/bin:$PATH"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ Failed to install uv${NC}"
        echo -e "${YELLOW}Please install manually from: https://github.com/astral-sh/uv${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} uv is installed"

# Sync dependencies with uv
echo -e "${CYAN}📦 Syncing Python dependencies with uv...${NC}"
uv sync --python python3

# Make installer executable
chmod +x install.py

# Run the installer
echo -e "${CYAN}🚀 Launching hooliGAN-harness installer...${NC}"
echo ""
uv run python install.py

echo ""
echo -e "${GREEN}${BOLD}✨ Setup complete!${NC}"
