#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_DIR="${CAELUS_INSTALL_DIR:-${HOME}/Caelus}"
PYTHON_BIN="${CAELUS_PYTHON:-python3}"

fail() {
  printf 'Caelus installation failed: %s\n' "$1" >&2
  exit 1
}

case "$INSTALL_DIR" in
  ""|/|"$HOME") fail "CAELUS_INSTALL_DIR must name a dedicated application directory." ;;
esac

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3.10 or newer was not found."
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required."

mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/caelus" "$INSTALL_DIR/static" \
  "$INSTALL_DIR/templates" "$INSTALL_DIR/data"

if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
  cp "$SOURCE_DIR/Caelus.py" "$INSTALL_DIR/Caelus.py"
  cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"
  cp "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
  cp "$SOURCE_DIR/install.sh" "$INSTALL_DIR/install.sh"
  cp "$SOURCE_DIR/install.ps1" "$INSTALL_DIR/install.ps1"
  cp "$SOURCE_DIR/run_caelus.sh" "$INSTALL_DIR/run_caelus.sh"
  cp "$SOURCE_DIR/run_caelus.ps1" "$INSTALL_DIR/run_caelus.ps1"
  cp "$SOURCE_DIR/run_caelus.cmd" "$INSTALL_DIR/run_caelus.cmd"
  cp "$SOURCE_DIR"/caelus/*.py "$INSTALL_DIR/caelus/"
  cp -R "$SOURCE_DIR/static/." "$INSTALL_DIR/static/"
  cp -R "$SOURCE_DIR/templates/." "$INSTALL_DIR/templates/"
fi

if ! "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"; then
  fail "Could not create the virtual environment. On Debian, Raspberry Pi OS Bookworm, or Trixie, install python3-venv and run this installer again."
fi

"$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check \
  -r "$INSTALL_DIR/requirements.txt"
chmod +x "$INSTALL_DIR/run_caelus.sh"
chmod +x "$INSTALL_DIR/install.sh"

printf '\nCaelus was installed in %s\n' "$INSTALL_DIR"
printf 'Start it with: %s/run_caelus.sh\n' "$INSTALL_DIR"
printf 'Then open: http://127.0.0.1:8767\n'
printf 'Application data is preserved in: %s/data\n' "$INSTALL_DIR"
