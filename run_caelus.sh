#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  printf 'Caelus virtual environment is missing. Run %s/install.sh again.\n' "$RUNTIME_DIR" >&2
  exit 1
fi

cd "$RUNTIME_DIR"
exec "$PYTHON_BIN" "$RUNTIME_DIR/Caelus.py" "$@"
