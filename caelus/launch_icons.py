"""Install per-user click-to-launch icons without starting Caelus."""

import argparse
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

from caelus import __version__
from caelus.desktop import MACOS_LAUNCH_SERVICES, write_linux_app_launcher


MACOS_LAUNCHER_ID = "weather.caelus.Caelus.launcher"


def write_macos_app_launcher(runtime_dir: Path) -> Path:
    """Create a Finder application pointing to the selected installed runtime."""
    bundle = Path.home() / "Applications" / "Caelus.app"
    info = bundle / "Contents" / "Info.plist"
    if bundle.exists():
        if not info.is_file() or plistlib.loads(info.read_bytes()).get(
            "CFBundleIdentifier"
        ) != MACOS_LAUNCHER_ID:
            raise FileExistsError(f"Refusing to overwrite another application: {bundle}")
    executable_dir = bundle / "Contents" / "MacOS"
    resources = bundle / "Contents" / "Resources"
    executable_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    icon = runtime_dir / "static/icons/caelus-desktop-icon.icns"
    version = __version__.removeprefix("v0.")
    info.write_bytes(plistlib.dumps({
        "CFBundleDisplayName": "Caelus",
        "CFBundleName": "Caelus",
        "CFBundleExecutable": "Caelus",
        "CFBundleIdentifier": MACOS_LAUNCHER_ID,
        "CFBundleIconFile": icon.stem,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "NSLocalNetworkUsageDescription": (
            "Caelus connects to your Ecowitt gateway on the local network "
            "to read weather measurements and sensor battery status."
        ),
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CaelusInstallDirectory": str(runtime_dir),
    }))
    shutil.copyfile(icon, resources / icon.name)
    executable = executable_dir / "Caelus"
    native_launcher = runtime_dir / "static/launchers/caelus-macos-launcher"
    temporary_executable = executable.with_suffix(".tmp")
    shutil.copyfile(native_launcher, temporary_executable)
    temporary_executable.chmod(0o755)
    temporary_executable.replace(executable)
    script = resources / "launch.sh"
    script.write_text(
        "#!/bin/bash\n"
        f"runtime_dir={shlex.quote(str(runtime_dir))}\n"
        'log_file="$runtime_dir/data/desktop-launch.log"\n'
        'if "$runtime_dir/run_caelus_gui.sh" "$@" >>"$log_file" 2>&1; then\n'
        '  exit 0\n'
        'fi\n'
        '/usr/bin/osascript - "$log_file" <<\'APPLESCRIPT\'\n'
        'on run argv\n'
        '  display alert "Caelus could not start" message '
        '("Run the installer again to repair the application. Details: " & item 1 of argv) as critical\n'
        'end run\n'
        'APPLESCRIPT\n'
        'exit 1\n', encoding="utf-8",
    )
    # Sign after writing resources so the native identity and resource seal agree.
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", "--identifier",
         MACOS_LAUNCHER_ID, str(bundle)],
        check=True, capture_output=True, text=True,
    )
    try:
        subprocess.run(
            [str(MACOS_LAUNCH_SERVICES), "-f", str(bundle)],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Caelus could not refresh its Finder launcher metadata: {exc}", file=sys.stderr)
    return bundle


def main() -> int:
    """Create the selected runtime's launch icon on macOS or Linux."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_dir", type=Path)
    args = parser.parse_args()
    runtime_dir = args.runtime_dir.resolve()
    try:
        if not (runtime_dir / "run_caelus_gui.sh").is_file():
            raise FileNotFoundError(f"Installed GUI launcher is missing: {runtime_dir}")
        if sys.platform == "darwin":
            path = write_macos_app_launcher(runtime_dir)
        elif sys.platform.startswith("linux"):
            path = write_linux_app_launcher(runtime_dir)
        else:
            parser.error("Windows shortcuts are provided by install.ps1.")
        print(f"Click-to-launch icon: {path}")
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.CalledProcessError) as exc:
        print(f"Caelus launch icon could not be updated: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
