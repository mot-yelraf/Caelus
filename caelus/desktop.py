"""Launch Caelus in a native pywebview desktop window."""

from __future__ import annotations

import ctypes
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from caelus import __version__


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ICON_PATH = PROJECT_ROOT / "static" / "icons" / "caelus-desktop-icon.png"
WINDOWS_ICON_PATH = PROJECT_ROOT / "static" / "icons" / "caelus-desktop-icon.ico"
MACOS_ICON_PATH = PROJECT_ROOT / "static" / "icons" / "caelus-desktop-icon.icns"
LINUX_APP_ID = "weather.caelus.Caelus"
MACOS_APP_NAME = "Caelus"
MACOS_BUNDLE_IDENTIFIER = "weather.caelus.Caelus"
MACOS_RELAUNCH_MARKER = "CAELUS_MACOS_APP_RELAUNCHED"
MACOS_HEADLESS_MARKER = "CAELUS_GUI_HEADLESS"
MACOS_LAUNCH_SERVICES = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)

DEFAULT_WINDOW_WIDTH = 1600
DEFAULT_WINDOW_HEIGHT = 1000
DEFAULT_MIN_WIDTH = 1100
DEFAULT_MIN_HEIGHT = 700

_windows_icon: Any = None
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _macos_app_bundle_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / MACOS_APP_NAME
        / f"{MACOS_APP_NAME}.app"
    )


def configure_macos_app_bundle(bundle_path: Path | None = None) -> Path:
    """Create the per-user app bundle that supplies Caelus's process identity."""
    app_bundle = bundle_path or _macos_app_bundle_path()
    contents_dir = app_bundle / "Contents"
    executable_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    executable_path = executable_dir / MACOS_APP_NAME
    icon_path = resources_dir / MACOS_ICON_PATH.name
    plist_path = contents_dir / "Info.plist"
    executable_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    plist_data = plistlib.dumps(
        {
            "CFBundleDisplayName": MACOS_APP_NAME,
            "CFBundleName": MACOS_APP_NAME,
            "CFBundleExecutable": MACOS_APP_NAME,
            "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
            "CFBundleIconFile": MACOS_ICON_PATH.name,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": __version__.removeprefix("v"),
            "CFBundleVersion": __version__.removeprefix("v"),
            "NSHighResolutionCapable": True,
        }
    )
    if not plist_path.is_file() or plist_path.read_bytes() != plist_data:
        temporary_plist = plist_path.with_suffix(".plist.tmp")
        temporary_plist.write_bytes(plist_data)
        temporary_plist.replace(plist_path)

    if not executable_path.is_symlink() or os.readlink(executable_path) != sys.executable:
        temporary_executable = executable_path.with_name(f".{MACOS_APP_NAME}.tmp")
        temporary_executable.unlink(missing_ok=True)
        temporary_executable.symlink_to(sys.executable)
        temporary_executable.replace(executable_path)

    if not icon_path.is_file() or icon_path.read_bytes() != MACOS_ICON_PATH.read_bytes():
        temporary_icon = icon_path.with_suffix(".icns.tmp")
        shutil.copyfile(MACOS_ICON_PATH, temporary_icon)
        temporary_icon.replace(icon_path)

    os.utime(app_bundle, None)
    try:
        result = subprocess.run(
            [str(MACOS_LAUNCH_SERVICES), "-f", str(app_bundle)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode:
            print(
                "Caelus could not refresh its macOS LaunchServices metadata.",
                file=sys.stderr,
            )
    except OSError as exc:
        print(f"Caelus could not refresh its macOS LaunchServices metadata: {exc}", file=sys.stderr)
    return app_bundle


def relaunch_with_macos_app_identity() -> bool:
    """Re-execute an unfrozen macOS GUI launch from Caelus's app bundle."""
    if (
        sys.platform != "darwin"
        or getattr(sys, "frozen", False)
        or hasattr(sys, "_MEIPASS")
        or _environment_flag(MACOS_HEADLESS_MARKER)
        or _environment_flag(MACOS_RELAUNCH_MARKER)
    ):
        return False

    try:
        app_bundle = configure_macos_app_bundle()
        executable_path = app_bundle / "Contents" / "MacOS" / MACOS_APP_NAME
        environment = os.environ.copy()
        environment[MACOS_RELAUNCH_MARKER] = "1"
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(PROJECT_ROOT), existing_pythonpath) if part
        )
        os.execve(
            executable_path,
            [str(executable_path), "-m", "caelus.desktop", *sys.argv[1:]],
            environment,
        )
    except OSError as exc:
        print(f"Caelus could not establish its macOS application identity: {exc}", file=sys.stderr)
    return False


def _base_url() -> str:
    configured = os.environ.get("CAELUS_GUI_URL")
    if configured:
        return configured.rstrip("/") + "/"
    port = os.environ.get("CAELUS_HTTP_PORT", "8767")
    return f"http://127.0.0.1:{port}/"


def _int_env(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _available_screen_size() -> tuple[int, int] | None:
    """Return the primary display's usable size when the platform exposes it."""
    try:
        if sys.platform == "darwin":
            from AppKit import NSScreen

            screen = NSScreen.mainScreen()
            if screen is not None:
                size = screen.visibleFrame().size
                return int(size.width), int(size.height)
        elif sys.platform == "win32":
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        elif sys.platform.startswith("linux"):
            import gi

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk

            display = Gdk.Display.get_default()
            if display is not None:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor is not None:
                    workarea = monitor.get_workarea()
                    return int(workarea.width), int(workarea.height)
    except Exception:
        pass
    return None


def _window_geometry() -> dict[str, int | None]:
    width = max(640, _int_env("CAELUS_GUI_WIDTH", DEFAULT_WINDOW_WIDTH) or DEFAULT_WINDOW_WIDTH)
    height = max(480, _int_env("CAELUS_GUI_HEIGHT", DEFAULT_WINDOW_HEIGHT) or DEFAULT_WINDOW_HEIGHT)
    screen_size = _available_screen_size()
    if screen_size is not None:
        width = min(width, screen_size[0])
        height = min(height, screen_size[1])
    return {
        "width": width,
        "height": height,
        "x": _int_env("CAELUS_GUI_X", None),
        "y": _int_env("CAELUS_GUI_Y", None),
    }


def _is_healthy(base_url: str, timeout: float = 1.0) -> bool:
    health_url = base_url.rstrip("/") + "/healthz"
    try:
        # A loopback health probe must never be satisfied by an HTTP proxy.
        with _direct_opener.open(health_url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_health(base_url: str, process: subprocess.Popen[Any] | None) -> bool:
    retries = max(1, _int_env("CAELUS_GUI_RETRIES", 120) or 120)
    delay = max(0.0, _float_env("CAELUS_GUI_RETRY_DELAY", 0.25))
    for _ in range(retries):
        if _is_healthy(base_url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(delay)
    return False


def _start_server() -> subprocess.Popen[Any]:
    """Start Caelus with the current interpreter, preserving venv ownership."""
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "Caelus.py")],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
    )


def _stop_owned_server(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _desktop_exec_arg(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def configure_linux_app_identity() -> Path | None:
    """Install the per-user Linux desktop identity used by GTK and Wayland."""
    if not sys.platform.startswith("linux"):
        return None

    try:
        from gi.repository import GLib

        GLib.set_prgname(LINUX_APP_ID)
        GLib.set_application_name("Caelus")
    except Exception as exc:
        print(f"Caelus could not set its Linux application ID: {exc}", file=sys.stderr)

    data_root = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ).expanduser()
    applications_dir = data_root / "applications"
    icons_dir = data_root / "icons" / "hicolor" / "512x512" / "apps"
    desktop_path = applications_dir / f"{LINUX_APP_ID}.desktop"
    themed_icon_path = icons_dir / f"{LINUX_APP_ID}.png"
    launcher_path = PROJECT_ROOT / "run_caelus_gui.sh"
    desktop_text = "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=Caelus",
            "Comment=Open the Caelus living weather dashboard",
            f"Exec={_desktop_exec_arg(str(launcher_path))}",
            f"Path={PROJECT_ROOT}",
            f"Icon={DESKTOP_ICON_PATH}",
            "Terminal=false",
            "StartupNotify=true",
            f"StartupWMClass={LINUX_APP_ID}",
            "",
        )
    )

    try:
        applications_dir.mkdir(parents=True, exist_ok=True)
        icons_dir.mkdir(parents=True, exist_ok=True)
        if (
            not themed_icon_path.is_file()
            or themed_icon_path.read_bytes() != DESKTOP_ICON_PATH.read_bytes()
        ):
            temporary_icon = themed_icon_path.with_suffix(".png.tmp")
            shutil.copyfile(DESKTOP_ICON_PATH, temporary_icon)
            temporary_icon.replace(themed_icon_path)
        if not desktop_path.is_file() or desktop_path.read_text(encoding="utf-8") != desktop_text:
            temporary_desktop = desktop_path.with_suffix(".desktop.tmp")
            temporary_desktop.write_text(desktop_text, encoding="utf-8")
            temporary_desktop.replace(desktop_path)
    except OSError as exc:
        print(f"Caelus could not install its Linux desktop entry: {exc}", file=sys.stderr)
        return None
    return desktop_path


def set_macos_app_icon() -> None:
    """Set the running Cocoa application's Dock and app-switcher icon."""
    if not DESKTOP_ICON_PATH.is_file():
        return
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper

        def apply_icon() -> None:
            icon = NSImage.alloc().initWithContentsOfFile_(str(DESKTOP_ICON_PATH))
            if icon is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(icon)

        AppHelper.callAfter(apply_icon)
    except Exception as exc:
        print(f"Caelus could not set its macOS application icon: {exc}", file=sys.stderr)


def set_windows_app_icon(window: Any) -> None:
    """Set the WinForms window and taskbar icon after native creation."""
    global _windows_icon
    if not WINDOWS_ICON_PATH.is_file() or window.native is None:
        return
    try:
        from System.Drawing import Icon

        _windows_icon = Icon(str(WINDOWS_ICON_PATH))
        window.native.Icon = _windows_icon
    except Exception as exc:
        print(f"Caelus could not set its Windows application icon: {exc}", file=sys.stderr)


def main() -> int:
    """Start or attach to Caelus and open its native desktop window."""
    relaunch_with_macos_app_identity()
    base_url = _base_url()
    owned_server: subprocess.Popen[Any] | None = None
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

    if sys.platform.startswith("linux"):
        os.environ.setdefault("GDK_BACKEND", "wayland,x11")
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            print("Caelus GUI not started: no DISPLAY or WAYLAND_DISPLAY is set.", file=sys.stderr)
            return 1
        configure_linux_app_identity()

    try:
        import webview
    except Exception as exc:
        print(f"Caelus GUI not started: pywebview import failed: {exc}", file=sys.stderr)
        return 1

    if not _is_healthy(base_url):
        if os.environ.get("CAELUS_GUI_URL"):
            print(f"Caelus GUI not started: {base_url.rstrip('/')} is not ready.", file=sys.stderr)
            return 1
        try:
            owned_server = _start_server()
        except OSError as exc:
            print(f"Caelus GUI could not start its server: {exc}", file=sys.stderr)
            return 1

    if not _wait_for_health(base_url, owned_server):
        _stop_owned_server(owned_server)
        print(f"Caelus GUI not started: {base_url.rstrip('/')} did not become ready.", file=sys.stderr)
        return 1

    try:
        geometry = _window_geometry()
        window = webview.create_window(
            "Caelus · Living Weather",
            base_url,
            width=geometry["width"],
            height=geometry["height"],
            x=geometry["x"],
            y=geometry["y"],
            min_size=(
                min(DEFAULT_MIN_WIDTH, int(geometry["width"])),
                min(DEFAULT_MIN_HEIGHT, int(geometry["height"])),
            ),
            resizable=True,
            frameless=False,
            confirm_close=True,
        )
        if sys.platform == "darwin":
            window.events.shown += set_macos_app_icon
            webview.start()
        elif sys.platform == "win32":
            window.events.shown += lambda: set_windows_app_icon(window)
            webview.start()
        elif sys.platform.startswith("linux"):
            webview.start(gui="gtk", icon=str(DESKTOP_ICON_PATH))
        else:
            webview.start()
    finally:
        _stop_owned_server(owned_server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
