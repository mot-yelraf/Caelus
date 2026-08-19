#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="${CAELUS_PYTHON:-python3}"
DEFAULT_INSTALL_DIR="${HOME}/Caelus"
INSTALL_STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/caelus"
INSTALL_STATE_FILE="${INSTALL_STATE_DIR}/install-location"

fail() {
  printf 'Caelus installation failed: %s\n' "$1" >&2
  exit 1
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3.10 or newer was not found."
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required."

remembered_install_dir=""
if [ -f "$INSTALL_STATE_FILE" ]; then
  IFS= read -r remembered_install_dir < "$INSTALL_STATE_FILE" || true
fi
case "$remembered_install_dir" in
  ""|/) remembered_install_dir="$DEFAULT_INSTALL_DIR" ;;
esac

choose_install_location() {
  initial_location="$1"
  case "$(uname -s)" in
    Darwin)
      osascript - "$initial_location" <<'APPLESCRIPT'
on run argv
  set initialFolder to POSIX file (item 1 of argv)
  set chosenFolder to choose folder with prompt "Choose the Caelus folder or a parent folder. If needed, a Caelus folder will be created." default location initialFolder
  return POSIX path of chosenFolder
end run
APPLESCRIPT
      ;;
    Linux)
      if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null 2>&1; then
        zenity --file-selection --directory --title="Choose the Caelus folder or its parent" --filename="${initial_location}/"
        return
      fi
      if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v kdialog >/dev/null 2>&1; then
        kdialog --getexistingdirectory "$initial_location" --title "Choose the Caelus folder or its parent"
        return
      fi
      if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        return 2
      fi
      "$PYTHON_BIN" - "$initial_location" <<'PYTHON'
import sys

try:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    selected = filedialog.askdirectory(
        title="Choose the Caelus folder or its parent",
        initialdir=sys.argv[1],
        mustexist=True,
    )
    root.destroy()
except Exception:
    raise SystemExit(2)

if not selected:
    raise SystemExit(1)
print(selected)
PYTHON
      ;;
    *) return 2 ;;
  esac
}

resolve_selected_install_dir() {
  selected_location="${1%/}"
  [ -n "$selected_location" ] || selected_location="/"
  selected_name="$(basename -- "$selected_location")"
  case "$selected_name" in
    [Cc][Aa][Ee][Ll][Uu][Ss]) printf '%s\n' "$selected_location" ;;
    *) printf '%s/Caelus\n' "$selected_location" ;;
  esac
}

if [ "${CAELUS_INSTALL_DIR+x}" = "x" ]; then
  INSTALL_DIR="$CAELUS_INSTALL_DIR"
else
  initial_location="$remembered_install_dir"
  if [ ! -d "$initial_location" ]; then
    initial_location="$(dirname -- "$remembered_install_dir")"
  fi
  if [ ! -d "$initial_location" ]; then
    initial_location="$HOME"
  fi
  selection_status=0
  selected_location="$(choose_install_location "$initial_location")" || selection_status=$?
  if [ "$selection_status" -eq 1 ]; then
    fail "Installation was cancelled."
  elif [ "$selection_status" -eq 0 ] && [ -n "$selected_location" ]; then
    INSTALL_DIR="$(resolve_selected_install_dir "$selected_location")"
  elif [ -t 0 ]; then
    printf 'Choose the Caelus folder or its parent [%s] ' "$initial_location"
    IFS= read -r selected_location
    selected_location="${selected_location:-$initial_location}"
    INSTALL_DIR="$(resolve_selected_install_dir "$selected_location")"
  else
    INSTALL_DIR="$remembered_install_dir"
    printf 'No graphical folder chooser is available; using %s\n' "$INSTALL_DIR"
  fi
fi

case "$INSTALL_DIR" in
  ""|/|"$HOME") fail "The install location must name a dedicated application directory." ;;
  /*) ;;
  *) fail "The install location must be an absolute path." ;;
esac
mkdir -p "$INSTALL_DIR"
INSTALL_DIR="$(CDPATH= cd -- "$INSTALL_DIR" && pwd -P)"
case "$INSTALL_DIR" in
  /|"$HOME") fail "The install location must name a dedicated application directory." ;;
esac

mkdir -p "$INSTALL_DIR/caelus" "$INSTALL_DIR/static" \
  "$INSTALL_DIR/templates" "$INSTALL_DIR/data"

if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
  cp "$SOURCE_DIR/Caelus.py" "$INSTALL_DIR/Caelus.py"
  cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"
  cp "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
  cp "$SOURCE_DIR/install.sh" "$INSTALL_DIR/install.sh"
  cp "$SOURCE_DIR/install.ps1" "$INSTALL_DIR/install.ps1"
  cp "$SOURCE_DIR/run_caelus.sh" "$INSTALL_DIR/run_caelus.sh"
  cp "$SOURCE_DIR/run_caelus_gui.sh" "$INSTALL_DIR/run_caelus_gui.sh"
  cp "$SOURCE_DIR/run_caelus.ps1" "$INSTALL_DIR/run_caelus.ps1"
  cp "$SOURCE_DIR/run_caelus_gui.ps1" "$INSTALL_DIR/run_caelus_gui.ps1"
  cp "$SOURCE_DIR/run_caelus.cmd" "$INSTALL_DIR/run_caelus.cmd"
  cp "$SOURCE_DIR/run_caelus_gui.cmd" "$INSTALL_DIR/run_caelus_gui.cmd"
  cp "$SOURCE_DIR"/caelus/*.py "$INSTALL_DIR/caelus/"
  cp -R "$SOURCE_DIR/static/." "$INSTALL_DIR/static/"
  cp -R "$SOURCE_DIR/templates/." "$INSTALL_DIR/templates/"
fi

if [ "$(uname -s)" = "Linux" ]; then
  # GTK and WebKit are supplied by the distribution and must be visible inside
  # the private environment on Linux and Raspberry Pi OS.
  "$PYTHON_BIN" -m venv --system-site-packages "$INSTALL_DIR/.venv" \
    || fail "Could not create the virtual environment. Install python3-venv and run this installer again."
else
  "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv" \
    || fail "Could not create the virtual environment. Install Python 3 venv support and run this installer again."
fi

"$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check \
  -r "$INSTALL_DIR/requirements.txt"
"$INSTALL_DIR/.venv/bin/python" -c 'import webview' \
  || fail "pywebview could not be imported after installation."

if [ "$(uname -s)" = "Linux" ]; then
  "$INSTALL_DIR/.venv/bin/python" -c \
    "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1'); from gi.repository import Gtk, WebKit2" \
    || fail "GTK/WebKit is missing. On Debian, Ubuntu, or Raspberry Pi OS install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 and run this installer again."
fi
chmod +x "$INSTALL_DIR/run_caelus.sh"
chmod +x "$INSTALL_DIR/run_caelus_gui.sh"
chmod +x "$INSTALL_DIR/install.sh"

mkdir -p "$INSTALL_STATE_DIR"
install_state_temp="${INSTALL_STATE_FILE}.tmp.$$"
printf '%s\n' "$INSTALL_DIR" > "$install_state_temp"
mv "$install_state_temp" "$INSTALL_STATE_FILE"

printf '\nCaelus was installed in %s\n' "$INSTALL_DIR"
printf 'Start the desktop app with: %s/run_caelus_gui.sh\n' "$INSTALL_DIR"
printf 'Start the headless server with: %s/run_caelus.sh\n' "$INSTALL_DIR"
printf 'Open locally: http://127.0.0.1:8767\n'
printf 'Open on your LAN: http://<this-computer-LAN-IP>:8767\n'
printf 'Application data is preserved in: %s/data\n' "$INSTALL_DIR"
