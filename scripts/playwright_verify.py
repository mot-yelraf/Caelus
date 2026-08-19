"""Run the host-side Chromium verification used by the pre-commit gate."""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:
    raise SystemExit(
        "Playwright is required by the commit gate. Run: "
        "python3 -m pip install -r requirements-dev.txt && "
        "python3 -m playwright install chromium"
    )


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test-results" / "playwright"


def available_port() -> int:
    """Reserve an available loopback port for the deterministic test app."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_server(process: subprocess.Popen[bytes], base_url: str) -> None:
    """Wait until the deterministic app is healthy or fail with its log path."""
    for _ in range(50):
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Browser-test server failed to start; see {RESULTS / 'server.log'}")


def verify_dashboard(page: Page, base_url: str) -> None:
    """Exercise core UI interactions and collect browser/runtime failures."""
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_first_party_requests: list[str] = []

    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "requestfailed",
        lambda request: failed_first_party_requests.append(
            f"{request.method} {request.url}: {request.failure}"
        )
        if request.url.startswith(base_url)
        else None,
    )
    page.route("https://embed.windy.com/**", lambda route: route.abort())

    response = page.goto(base_url, wait_until="domcontentloaded")
    assert response is not None and response.ok, "Dashboard did not return HTTP success"
    page.wait_for_selector("main.dashboard-shell")
    assert page.title() == "Caelus · Living Weather"
    assert page.locator('[data-reading-field="temperature"]').inner_text() == "72.5"

    page.locator("[data-open-settings]").click()
    settings = page.locator("#settingsDialog")
    assert settings.evaluate("dialog => dialog.open")
    station_tab = page.locator('[data-settings-pane="station"]')
    station_tab.focus()
    station_tab.press("ArrowDown")
    assert page.locator('[data-pane="location"]').is_visible()
    page.locator("[data-close-settings]").first.click()
    assert not settings.evaluate("dialog => dialog.open")

    page.locator("[data-open-graph]").click()
    graph = page.locator("#graphDialog")
    assert graph.evaluate("dialog => dialog.open")
    page.locator("[data-close-graph]").click()
    assert not graph.evaluate("dialog => dialog.open")

    if console_errors or page_errors or failed_first_party_requests:
        details = [
            *(f"console: {error}" for error in console_errors),
            *(f"page: {error}" for error in page_errors),
            *(f"request: {error}" for error in failed_first_party_requests),
        ]
        raise AssertionError("Browser errors detected:\n" + "\n".join(details))


def run_browser_check(base_url: str) -> None:
    """Launch Chromium and retain diagnostics for failed checks."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            verify_dashboard(page, base_url)
        except Exception:
            page.screenshot(path=RESULTS / "failure.png", full_page=True)
            context.tracing.stop(path=RESULTS / "trace.zip")
            raise
        else:
            context.tracing.stop()
        finally:
            browser.close()


def main() -> None:
    """Start the test app, run verification, and always stop the app."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    port = available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["CAELUS_PLAYWRIGHT_PORT"] = str(port)
    with (RESULTS / "server.log").open("wb") as server_log:
        process = subprocess.Popen(
            [sys.executable, "-m", "scripts.playwright_app"],
            cwd=ROOT,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_server(process, base_url)
            run_browser_check(base_url)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    print("Host-side Playwright verification passed.")


if __name__ == "__main__":
    main()
