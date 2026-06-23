#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python_bin="${PYTHON:-python3}"
venv_dir=".venv"

if [ ! -x "$venv_dir/bin/python" ]; then
  echo "Creating $venv_dir"
  "$python_bin" -m venv "$venv_dir"
fi

echo "Installing Python requirements into $venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install -r requirements.txt

if ! command -v blueutil >/dev/null 2>&1 && ! command -v BluetoothConnector >/dev/null 2>&1; then
  echo
  echo "Bluetooth connect helper not found."
  echo "Install the recommended helper with: brew install blueutil"
  echo
fi

exec "$venv_dir/bin/kmautoconnect" setup "$@"
