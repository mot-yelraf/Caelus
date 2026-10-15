"""Read the gateway from a fresh process when the server's LAN access fails."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

MAX_RESPONSE_BYTES = 512 * 1024
RECOVERY_TIMEOUT_SECONDS = 8
READ_ENDPOINTS = {
    "get_version", "get_network_info", "get_sensors_info",
    "get_livedata_info", "get_rain_totals",
}


def request_in_fresh_process(base_url: str, endpoint: str, params: dict) -> Any:
    """Run one bounded, read-only request using the installed interpreter."""
    if getattr(sys, "frozen", False):
        raise RuntimeError("Fresh-process gateway recovery requires a Python runtime.")
    result = subprocess.run(
        [sys.executable, "-m", "caelus.gateway_recovery"],
        input=json.dumps({"base_url": base_url, "endpoint": endpoint, "params": params}),
        capture_output=True,
        text=True,
        timeout=RECOVERY_TIMEOUT_SECONDS,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Gateway recovery worker exited with code {result.returncode}.")
    if len(result.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Gateway recovery response was unexpectedly large.")
    reply = json.loads(result.stdout)
    if not isinstance(reply, dict) or "payload" not in reply:
        error = reply.get("error") if isinstance(reply, dict) else None
        raise RuntimeError(error or "Gateway recovery worker returned an invalid response.")
    return reply["payload"]


def main() -> None:
    """Serve a single JSON request on stdin; never load or change settings."""
    from caelus.gateway import normalize_gateway_base_url

    try:
        request = json.load(sys.stdin)
        base_url = normalize_gateway_base_url(request["base_url"])
        endpoint = request["endpoint"]
        params = request["params"]
        if endpoint not in READ_ENDPOINTS or not isinstance(params, dict):
            raise ValueError("Unsupported gateway recovery request.")
        with requests.get(
            f"{base_url}/{endpoint}", params=params or None, timeout=5,
            stream=True, allow_redirects=False,
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Gateway response was unexpectedly large.")
            payload = json.loads(content)
        reply = json.dumps({"payload": payload})
        if len(reply.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("Gateway recovery response was unexpectedly large.")
    except Exception as exc:
        reply = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    print(reply)


if __name__ == "__main__":
    main()
