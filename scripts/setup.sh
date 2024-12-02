#!/usr/bin/env bash

# Set-up the development environment

# Stop on errors
set -e

cd "$(dirname "$0")/.."

env_name=${1:-".venv"}

if [ -d "$env_name" ]; then
  echo "Virtual environment '$env_name' already exists."
else
  echo "Creating Virtual environment..."
  python -m venv .venv
fi
echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing development dependencies..."

pip install --upgrade pip
pip install -e "."
pip install -e ".[test]"
pre-commit install