import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unix_installer_and_launcher_have_valid_bash_syntax() -> None:
    for name in ("install.sh", "run_caelus.sh"):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / name)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_unix_installer_preserves_runtime_state_and_uses_private_venv() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert '${CAELUS_INSTALL_DIR:-${HOME}/Caelus}' in script
    assert 'mkdir -p "$INSTALL_DIR"' in script
    assert '"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"' in script
    assert '"$INSTALL_DIR/.venv/bin/python" -m pip install' in script
    assert 'cp "$SOURCE_DIR/data' not in script
    assert 'rm -' not in script


def test_unix_install_layout_is_idempotent_and_preserves_data(tmp_path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -eu
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  chmod +x "$3/bin/python"
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    runtime = tmp_path / "runtime"
    environment = {
        **os.environ,
        "CAELUS_INSTALL_DIR": str(runtime),
        "CAELUS_PYTHON": str(fake_python),
    }

    subprocess.run(
        [str(ROOT / "install.sh")],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    marker = runtime / "data" / "preserve-me.txt"
    marker.write_text("historical data", encoding="utf-8")
    subprocess.run(
        [str(ROOT / "install.sh")],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert (runtime / ".venv" / "bin" / "python").exists()
    assert (runtime / "caelus" / "app.py").exists()
    assert (runtime / "static" / "dashboard.js").exists()
    assert (runtime / "templates" / "dashboard.html").exists()
    assert (runtime / "run_caelus.sh").stat().st_mode & 0o111
    assert marker.read_text(encoding="utf-8") == "historical data"


def test_windows_installer_uses_user_runtime_and_private_venv() -> None:
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "run_caelus.cmd").read_text(encoding="utf-8")

    assert 'Join-Path $env:USERPROFILE "Caelus"' in installer
    assert '-m venv (Join-Path $InstallDir ".venv")' in installer
    assert 'pip install --disable-pip-version-check' in installer
    assert 'Copy-Item (Join-Path $SourceDir "data' not in installer
    assert ".venv\\Scripts\\python.exe" in launcher


def test_requirements_are_pinned_and_avoid_native_uvicorn_extras() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert requirements
    assert all("==" in line for line in requirements if line.strip())
    assert "uvicorn==0.34.3" in requirements
    assert "skyfield==1.54" in requirements
    assert "skyfield-data==5.0.0" in requirements
    assert not any("uvicorn[standard]" in line for line in requirements)
