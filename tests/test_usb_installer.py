"""Verify privileged USB setup through fake system commands, never host changes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def fake_commands(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "commands.jsonl"
    rule = tmp_path / "installed-rule"
    source = f"""#!{sys.executable}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['USB_TEST_LOG'], 'a') as handle:
    handle.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'id':
    print(os.environ.get('USB_TEST_UID', '0'))
elif name == 'getent':
    raise SystemExit(0 if sys.argv[-1] == 'weather' else 2)
elif name == 'apt-get':
    raise SystemExit(int(os.environ.get('USB_TEST_APT_STATUS', '0')))
elif name == 'install':
    pathlib.Path(os.environ['USB_TEST_RULE']).write_text(pathlib.Path(sys.argv[-2]).read_text())
elif name == 'cmp':
    raise SystemExit(1)
"""
    for name in ("id", "getent", "apt-get", "udevadm", "mkdir", "install", "cmp"):
        command = directory / name
        command.write_text(source)
        command.chmod(0o755)
    return (
        log,
        rule,
        {
            **os.environ,
            "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}",
            "USB_TEST_LOG": str(log),
            "USB_TEST_RULE": str(rule),
        },
    )


def run_helper(tmp_path, *, group="weather", native="1", overrides=None):
    log, rule, env = fake_commands(tmp_path)
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "scripts/configure_acurite_usb.sh"), group, native],
        text=True,
        capture_output=True,
        env={**env, **(overrides or {})},
    )
    calls = (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )
    return result, calls, rule


def test_helper_limits_permissions_to_acurite_and_reloads_udev(tmp_path):
    result, calls, rule = run_helper(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (
        rule.read_text()
        == 'SUBSYSTEM=="usb", ATTR{{idVendor}}=="24c0", ATTR{{idProduct}}=="0003", GROUP="weather", MODE="0660"\nSUBSYSTEM=="usb", ATTR{{idVendor}}=="0fde", ATTR{{idProduct}}=="ca01", GROUP="weather", MODE="0660"\n'.replace(
            "{{", "{"
        ).replace("}}", "}")
    )
    assert [
        "apt-get",
        "install",
        "-y",
        "--no-install-recommends",
        "libusb-1.0-0",
    ] in calls
    assert ["udevadm", "control", "--reload-rules"] in calls
    install = next(call for call in calls if call[0] == "install")
    assert install[1:7] == ["-o", "root", "-g", "root", "-m", "0644"]
    assert install[-1] == "/etc/udev/rules.d/70-caelus-acurite.rules"


def test_helper_skips_package_install_when_backend_is_present(tmp_path):
    result, calls, _ = run_helper(tmp_path, native="0")
    assert result.returncode == 0
    assert not any(call[0] == "apt-get" for call in calls)


@pytest.mark.parametrize("group", ['bad"group', "../root", "missing-group"])
def test_helper_rejects_invalid_groups_before_system_changes(tmp_path, group):
    result, calls, rule = run_helper(tmp_path, group=group)
    assert result.returncode != 0
    assert not rule.exists()
    assert not any(call[0] in {"apt-get", "install", "udevadm"} for call in calls)


def test_helper_requires_admin_authorization(tmp_path):
    result, calls, rule = run_helper(tmp_path, overrides={"USB_TEST_UID": "1000"})
    assert result.returncode != 0 and not rule.exists()
    assert not any(call[0] == "apt-get" for call in calls)


def test_package_failure_does_not_claim_permissions_were_configured(tmp_path):
    result, calls, rule = run_helper(tmp_path, overrides={"USB_TEST_APT_STATUS": "1"})
    assert result.returncode != 0 and not rule.exists()
    assert not any(call[0] == "udevadm" for call in calls)


@pytest.mark.parametrize(
    "mode,authorization_status,expected_calls",
    [("auto", 0, 0), ("no", 0, 0), ("yes", 0, 1), ("yes", 1, 1)],
)
def test_linux_installer_requests_only_usb_helper_privileges(
    tmp_path, mode, authorization_status, expected_calls
):
    fake_bin = tmp_path / "commands"
    fake_bin.mkdir()
    auth_log = tmp_path / "authorization.jsonl"
    fake_python = fake_bin / "fake-python"
    fake_python.write_text("""#!/usr/bin/env bash
set -eu
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  for argument in "$@"; do venv_path="$argument"; done
  mkdir -p "$venv_path/bin"
  cp "$0" "$venv_path/bin/python"
  chmod +x "$venv_path/bin/python"
fi
exit 0
""")
    fake_python.chmod(0o755)
    mocks = {
        "uname": '#!/bin/sh\nprintf "Linux\\n"\n',
        "id": '#!/bin/sh\ncase "$1" in -u) printf "1000\\n" ;; *) printf "weather\\n" ;; esac\n',
        "sudo": f"""#!{sys.executable}
import json, os, sys
with open(os.environ['USB_AUTH_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
raise SystemExit(int(os.environ['USB_AUTH_STATUS']))
""",
    }
    for name, source in mocks.items():
        path = fake_bin / name
        path.write_text(source)
        path.chmod(0o755)
    runtime = tmp_path / "runtime"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "CAELUS_INSTALL_DIR": str(runtime),
        "CAELUS_PYTHON": str(fake_python),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "CAELUS_SETUP_ACURITE_USB": mode,
        "USB_AUTH_LOG": str(auth_log),
        "USB_AUTH_STATUS": str(authorization_status),
    }
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "SUDO_USER", "CAELUS_USB_USER"):
        environment.pop(key, None)
    result = subprocess.run(
        [str(ROOT / "install.sh")],
        env=environment,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    calls = (
        [json.loads(line) for line in auth_log.read_text().splitlines()]
        if auth_log.exists()
        else []
    )
    assert len(calls) == expected_calls
    if calls:
        assert calls[0] == [
            "-n",
            "/bin/sh",
            str(runtime / "scripts/configure_acurite_usb.sh"),
            "weather",
            "0",
        ]
    assert (runtime / ".venv/bin/python").exists()
    assert (runtime / "scripts/configure_acurite_usb.sh").exists()
    if authorization_status and mode == "yes":
        assert "system setup was not completed" in result.stderr
