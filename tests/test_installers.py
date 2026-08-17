import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import caelus.app


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("configured_host", "expected_host"),
    [(None, "0.0.0.0"), ("127.0.0.1", "127.0.0.1")],
)
def test_runtime_listens_on_the_lan_with_a_host_override(
    monkeypatch: pytest.MonkeyPatch, configured_host: str | None, expected_host: str
) -> None:
    calls: list[dict[str, object]] = []
    fake_app = object()
    fake_uvicorn = SimpleNamespace(
        run=lambda app, **kwargs: calls.append({"app": app, **kwargs})
    )
    monkeypatch.setattr(caelus.app, "create_app", lambda: fake_app)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.delenv("CAELUS_HTTP_HOST", raising=False)
    if configured_host is not None:
        monkeypatch.setenv("CAELUS_HTTP_HOST", configured_host)

    runpy.run_path(str(ROOT / "Caelus.py"), run_name="__main__")

    assert calls == [{"app": fake_app, "host": expected_host, "port": 8767, "log_level": "info"}]


def test_application_uses_lifespan_instead_of_removed_fastapi_event_helpers() -> None:
    source = (ROOT / "caelus" / "app.py").read_text(encoding="utf-8")

    assert "lifespan=lifespan" in source
    assert ".add_event_handler(" not in source


def test_unix_installer_and_launcher_have_valid_bash_syntax() -> None:
    for name in ("install.sh", "run_caelus.sh", "run_caelus_gui.sh"):
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
    assert '"$PYTHON_BIN" -m venv --system-site-packages "$INSTALL_DIR/.venv"' in script
    assert '"$INSTALL_DIR/.venv/bin/python" -m pip install' in script
    assert 'cp "$SOURCE_DIR/run_caelus_gui.sh"' in script
    assert 'cp "$SOURCE_DIR/data' not in script
    assert 'rm -' not in script


def test_unix_install_layout_is_idempotent_and_preserves_data(tmp_path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -eu
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  for argument in "$@"; do venv_path="$argument"; done
  mkdir -p "$venv_path/bin"
  cp "$0" "$venv_path/bin/python"
  chmod +x "$venv_path/bin/python"
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
    assert (runtime / "run_caelus_gui.sh").stat().st_mode & 0o111
    assert (runtime / "caelus" / "desktop.py").exists()
    assert (runtime / "static" / "icons" / "caelus-desktop-icon.png").exists()
    assert marker.read_text(encoding="utf-8") == "historical data"


def test_windows_installer_uses_user_runtime_and_private_venv() -> None:
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "run_caelus.cmd").read_text(encoding="utf-8")

    assert 'Join-Path $env:USERPROFILE "Caelus"' in installer
    assert '-m venv (Join-Path $InstallDir ".venv")' in installer
    assert 'pip install --disable-pip-version-check' in installer
    assert 'Copy-Item (Join-Path $SourceDir "data' not in installer
    assert ".venv\\Scripts\\python.exe" in launcher
    assert '"run_caelus_gui.cmd"' in installer
    assert (ROOT / "run_caelus_gui.ps1").is_file()


def test_requirements_are_pinned_and_avoid_native_uvicorn_extras() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert requirements
    assert all("==" in line for line in requirements if line.strip())
    assert "uvicorn==0.34.3" in requirements
    assert "skyfield==1.54" in requirements
    assert "skyfield-data==5.0.0" in requirements
    assert "pywebview==5.4" in requirements
    assert not any("uvicorn[standard]" in line for line in requirements)
