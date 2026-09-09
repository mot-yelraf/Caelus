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
    from playwright.sync_api import Page, expect, sync_playwright
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
        if message.type == "error" and "422" not in message.text
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
    assert page.locator(".pane-heading > span").count() == 0
    assert page.locator('link[rel="apple-touch-icon"]').get_attribute("sizes") == "180x180"
    icon_size = page.evaluate("""async () => {
        const icon = new Image();
        icon.src = document.querySelector('link[rel="apple-touch-icon"]').href;
        await icon.decode();
        return [icon.naturalWidth, icon.naturalHeight];
    }""")
    assert icon_size == [180, 180]
    assert page.locator('[data-reading-field="temperature"]').inner_text() == "72.5"

    # Daily ranges must fit within the tile's previous desktop/mobile footprint.
    assert page.locator("[data-open-forecast], #forecastDialog, .forecast-meta").count() == 0
    expect(page.locator(".forecast-day")).to_have_count(6)
    expect(page.locator(".forecast-day-humidity").first).to_have_text("RH 30–85%")
    expect(page.locator(".forecast-day-wind").first).to_have_text("Wind 0–12 mph")
    for width, maximum_height in ((1480, 550), (1024, 559), (760, 767), (390, 787)):
        page.set_viewport_size({"width": width, "height": 1200})
        panel = page.locator(".forecast-panel")
        bounds = panel.bounding_box()
        assert bounds and bounds["height"] <= maximum_height
        assert panel.evaluate("el => el.scrollHeight <= el.clientHeight")
        for card in page.locator(".forecast-day").all():
            assert card.evaluate("el => el.scrollWidth <= el.clientWidth")
        panel.screenshot(path=RESULTS / f"forecast-{width}.png")
    page.locator("[data-hourly-next]").click()
    expect(page.locator("[data-hourly-status]")).to_have_text("Hours 2–9 of 24")
    page.locator("[data-hourly-previous]").click()

    # Simulate settings saved by another device while this dashboard stays open.
    remote_save = page.context.request.post(f"{base_url}/settings", form={
        "csrf_token": "playwright-test-token", "settings_pane": "location",
        "location_name": "Remote station",
    })
    assert remote_save.ok
    expect(page.locator("#station-title")).to_have_text("Host verification")
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("[data-refresh-dashboard]").click()
    expect(page.locator("#station-title")).to_have_text("Remote station")

    for width in (1440, 390, 320):
        page.set_viewport_size({"width": width, "height": 1200})
        header = page.locator(".site-header")
        graph_button = header.locator("[data-open-graph]")
        settings_button = header.locator("[data-open-settings]")
        graph_bounds = graph_button.bounding_box()
        brand_bounds = header.locator(".brand").bounding_box()
        settings_bounds = settings_button.bounding_box()
        assert graph_bounds and brand_bounds and settings_bounds
        assert graph_bounds["x"] + graph_bounds["width"] <= brand_bounds["x"]
        assert brand_bounds["x"] + brand_bounds["width"] <= settings_bounds["x"]
        assert graph_bounds["x"] >= 0 and settings_bounds["x"] + settings_bounds["width"] <= width
        assert graph_bounds["height"] >= 44 and settings_bounds["height"] >= 44
        icon_bounds = header.locator(".brand-mark").bounding_box()
        assert icon_bounds
        for bounds in (graph_bounds, settings_bounds):
            assert bounds["width"] == icon_bounds["width"]
            assert bounds["height"] == icon_bounds["height"]
        glyph_size = graph_button.locator("img").bounding_box()
        assert glyph_size and abs(glyph_size["width"] - 30.24) < 0.1
        assert settings_button.locator("span").evaluate("el => getComputedStyle(el).fontSize") == "30.24px"
        assert graph_button.inner_text() == ""
        assert settings_button.inner_text() == "⚙"
        for button, bounds, glyph in (
            (graph_button, graph_bounds, graph_button.locator("img")),
            (settings_button, settings_bounds, settings_button.locator("span")),
        ):
            glyph_bounds = glyph.bounding_box()
            assert glyph_bounds
            assert abs(glyph_bounds["y"] + glyph_bounds["height"] / 2 - bounds["y"] - bounds["height"] / 2) < 1
            for hover in (False, True):
                if hover:
                    button.hover()
                style = button.evaluate("el => { const s = getComputedStyle(el); return [s.borderTopWidth, s.backgroundColor]; }")
                assert style == ["0px", "rgba(0, 0, 0, 0)"]
        page.mouse.move(0, 0)
        header.screenshot(path=RESULTS / f"header-{width}.png")
    page.set_viewport_size({"width": 1440, "height": 1200})

    page.locator("[data-open-settings]").click()
    settings = page.locator("#settingsDialog")
    assert settings.evaluate("dialog => dialog.open")
    expect(settings.locator(".modal-header .eyebrow")).to_contain_text("Caelus v0.")
    assert "v0." not in page.locator(".site-header").inner_text()
    expect(page.locator('[data-settings-pane]').first).to_have_text("Location")
    expect(page.locator('[data-pane="location"]')).to_be_visible()
    station_tab = page.locator('[data-settings-pane="station"]')
    station_tab.click()
    page.locator("#ecowittGatewayUrl").fill("http://192.0.2.42")
    station_tab.focus()
    station_tab.press("ArrowUp")
    assert page.locator('[data-pane="location"]').is_visible()
    # Saving re-renders the dashboard and keeps other panes' drafts intact.
    page.locator("#locationName").fill("Updated station")
    page.locator('[data-save-pane="location"]').click()
    expect(page.locator("#station-title")).to_have_text("Updated station")
    expect(page.locator('[data-pane="location"]')).to_be_visible()
    expect(page.locator("#ecowittGatewayUrl")).to_have_value("http://192.0.2.42")
    toast = page.locator("[data-settings-status]")
    expect(toast).to_have_text("Location saved.")
    bounds = toast.bounding_box()
    dialog_bounds = settings.bounding_box()
    assert bounds and dialog_bounds
    assert abs(bounds["x"] + bounds["width"] / 2 - dialog_bounds["x"] - dialog_bounds["width"] / 2) < 2
    assert 0 <= bounds["y"] - dialog_bounds["y"] < 30
    expect(toast).to_be_hidden(timeout=6500)
    page.locator('[data-settings-pane="forecast"]').click()
    page.locator('[name="forecast_provider"][value="open_meteo"]').check()
    page.locator('[data-save-pane="forecast"]').click()
    expect(page.locator(".provider-label")).to_have_text("open_meteo")
    expect(page.locator('[data-pane="forecast"]')).to_be_visible()
    expect(toast).to_have_text("Forecast saved.")
    # Server-side validation failures use the same toast and do not navigate.
    page.locator('[data-settings-pane="location"]').click()
    page.locator("#locationTimezone").fill("Invalid/Timezone")
    page.locator('[data-save-pane="location"]').click()
    expect(toast).to_have_class("settings-status is-error")
    expect(toast).to_be_visible()
    expect(page.locator("#station-title")).to_have_text("Updated station")
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
