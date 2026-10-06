"""Verify installed launch icons without accessing a real desktop session."""

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

import pytest

from caelus import launch_icons
from caelus.desktop import LINUX_APP_ID, write_linux_app_launcher


ROOT = Path(__file__).resolve().parents[1]


def make_runtime(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "data").mkdir()
    shutil.copytree(ROOT / "static/icons", path / "static/icons")
    shutil.copytree(ROOT / "static/launchers", path / "static/launchers")
    launcher = path / "run_caelus_gui.sh"
    launcher.write_text('#!/bin/bash\nprintf "%s\\n" "$PWD" "$@"\n')
    launcher.chmod(0o755)
    return path


def test_macos_bundle_launches_selected_runtime_and_updates_without_data_loss(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    runtime = make_runtime(tmp_path / "runtime 'with $ spaces")
    real_run = subprocess.run
    signing_calls = []
    monkeypatch.setattr(launch_icons.subprocess, "run", lambda *args, **kwargs: signing_calls.append((args, kwargs)))
    bundle = launch_icons.write_macos_app_launcher(runtime)
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    assert bundle == tmp_path / "Applications/Caelus.app"
    assert info["CFBundleIdentifier"] == launch_icons.MACOS_LAUNCHER_ID
    assert info["CaelusInstallDirectory"] == str(runtime)
    assert info["LSUIElement"] is True
    assert "Ecowitt gateway" in info["NSLocalNetworkUsageDescription"]
    assert signing_calls[0][0][0] == [
        "/usr/bin/codesign", "--force", "--sign", "-", "--identifier",
        launch_icons.MACOS_LAUNCHER_ID, str(bundle),
    ]
    icon = bundle / "Contents/Resources/caelus-desktop-icon.icns"
    assert icon.read_bytes() == (runtime / "static/icons/caelus-desktop-icon.icns").read_bytes()
    executable = bundle / "Contents/MacOS/Caelus"
    assert executable.read_bytes() == (runtime / "static/launchers/caelus-macos-launcher").read_bytes()
    # Exercise the resource script on all hosts; the native executable is macOS-only.
    real_run(["bash", str(bundle / "Contents/Resources/launch.sh"), "argument with spaces"], check=True, cwd=tmp_path)
    log = runtime / "data/desktop-launch.log"
    assert "argument with spaces" in log.read_text()
    second = make_runtime(tmp_path / "new runtime")
    assert launch_icons.write_macos_app_launcher(second) == bundle
    assert plistlib.loads((bundle / "Contents/Info.plist").read_bytes())["CaelusInstallDirectory"] == str(second)
    assert "argument with spaces" in log.read_text()


def test_macos_refuses_to_overwrite_an_unrelated_app(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bundle = tmp_path / "Applications/Caelus.app"
    bundle.mkdir(parents=True)
    marker = bundle / "user-file"
    marker.write_text("preserve")
    with pytest.raises(FileExistsError):
        launch_icons.write_macos_app_launcher(tmp_path)
    assert marker.read_text() == "preserve"


def test_linux_menu_entry_created_without_gtk_and_updated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    runtime = make_runtime(tmp_path / "runtime with spaces")
    entry = write_linux_app_launcher(runtime)
    text = entry.read_text()
    assert f'Exec="{runtime}/run_caelus_gui.sh"\n' in text
    assert f"Path={runtime}\n" in text
    assert "Terminal=false\n" in text
    assert f"Icon={LINUX_APP_ID}\n" in text
    icon = tmp_path / "xdg/icons/hicolor/512x512/apps" / f"{LINUX_APP_ID}.png"
    assert icon.read_bytes() == (runtime / "static/icons/caelus-desktop-icon.png").read_bytes()
    second = make_runtime(tmp_path / "new runtime")
    assert write_linux_app_launcher(second) == entry
    assert f'Exec="{second}/run_caelus_gui.sh"\n' in entry.read_text()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_unix_installer_creates_icon_during_install(tmp_path, platform) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codesign_stub = ""
    if sys.platform != "darwin":
        codesign_stub = "import subprocess; subprocess.run = lambda *args, **kwargs: None; "
    fake_python = fake_bin / "fake-python"
    fake_python.write_text('''#!/bin/bash
set -eu
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  for argument in "$@"; do venv_path="$argument"; done
  mkdir -p "$venv_path/bin"
  cp "$0" "$venv_path/bin/python"
  chmod +x "$venv_path/bin/python"
elif [ "${1:-}" = "-m" ] && [ "${2:-}" = "caelus.launch_icons" ]; then
  exec "$TEST_REAL_PYTHON" -c 'import os, runpy, sys; import caelus.desktop; sys.platform = os.environ["TEST_PLATFORM"]; sys.argv = ["launch_icons", sys.argv[1]]; CODE_SIGN_STUBrunpy.run_module("caelus.launch_icons", run_name="__main__")' "$3"
fi
'''.replace("CODE_SIGN_STUB", codesign_stub))
    fake_python.chmod(0o755)
    uname = fake_bin / "uname"
    uname.write_text(f'#!/bin/bash\nprintf "{ "Darwin" if platform == "darwin" else "Linux"}\\n"\n')
    uname.chmod(0o755)
    runtime = tmp_path / "installed runtime"
    env = {**os.environ, "HOME": str(tmp_path), "CAELUS_INSTALL_DIR": str(runtime),
           "CAELUS_PYTHON": str(fake_python), "XDG_DATA_HOME": str(tmp_path / "share"),
           "XDG_CONFIG_HOME": str(tmp_path / "config"), "TEST_REAL_PYTHON": sys.executable,
           "TEST_PLATFORM": platform, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    for _ in range(2):
        subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True, capture_output=True)
    if platform == "darwin":
        assert (tmp_path / "Applications/Caelus.app/Contents/MacOS/Caelus").is_file()
    else:
        assert (tmp_path / "share/applications" / f"{LINUX_APP_ID}.desktop").is_file()
    assert not (runtime / "data/settings.json").exists()
    assert not (runtime / "data/caelus.db").exists()


def test_windows_installer_creates_native_shortcuts() -> None:
    source = (ROOT / "install.ps1").read_text()
    assert '[Environment]::GetFolderPath("DesktopDirectory")' in source
    assert '[Environment]::GetFolderPath("Programs")' in source
    assert '$Shell.CreateShortcut($ShortcutPath)' in source
    assert 'Join-Path $ShortcutDirectory "Caelus.lnk"' in source
    assert 'Join-Path $InstallDir "run_caelus_gui.ps1"' in source
    assert '$Shortcut.WorkingDirectory = $InstallDir' in source
    assert 'static\\icons\\caelus-desktop-icon.ico' in source
    assert '$Shortcut.Save()' in source


@pytest.mark.skipif(sys.platform != "darwin", reason="Native launcher requires macOS")
def test_native_macos_launcher_is_signed_and_propagates_exit_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    runtime = make_runtime(tmp_path / "native runtime with spaces")
    launcher = runtime / "run_caelus_gui.sh"
    launcher.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit 7\n')
    bundle = launch_icons.write_macos_app_launcher(runtime)
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(bundle)], check=True)
    # Keep the test noninteractive: capture the error alert request in the log.
    script = bundle / "Contents/Resources/launch.sh"
    script.write_text(script.read_text().split('/usr/bin/osascript')[0] + 'exit 7\n')
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True, capture_output=True)
    result = subprocess.run([str(bundle / "Contents/MacOS/Caelus"), "argument with spaces"], check=False)
    assert result.returncode == 7
    assert "argument with spaces" in (runtime / "data/desktop-launch.log").read_text()
