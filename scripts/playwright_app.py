"""Serve deterministic Caelus data for the host-side Playwright gate."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from caelus.routes import register_routes
from caelus.settings import AppSettings
from caelus.theme_manager import ThemeManager


ROOT = Path(__file__).resolve().parents[1]
TEMP_DATA = TemporaryDirectory(prefix="caelus-playwright-")


class BrowserTestLogger:
    """Provide stable readings without creating or querying SQLite state."""

    def get_latest(self):
        return {
            "timestamp": "2026-08-19T18:00:00",
            "temperature": 72.5,
            "humidity": 48,
            "pressure": 1013.2,
            "wind_speed": 3.5,
            "wind_gust": 7.0,
            "wind_dir": 225,
        }

    def get_readings_since(self, cutoff):
        return []

    def export_readings(self, max_days, format, unit_system=None, pressure_unit="auto"):
        return "[]" if format == "json" else "timestamp"


class BrowserTestForecast:
    """Avoid remote forecast calls while preserving the dashboard contract."""

    def get(self, settings, *, force=False):
        return {
            "ok": False,
            "provider": settings.forecast_provider,
            "provider_label": "Browser test",
            "reason": "Deterministic browser verification",
            "hours": [],
            "days": [],
        }


class BrowserTestTask:
    def done(self):
        return False


class BrowserTestPoller:
    task = BrowserTestTask()

    def poll_once(self):
        return None

    def reset_schedule(self):
        return None


app = FastAPI(title="Caelus browser verification")
app.state.templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.state.theme_manager = ThemeManager(Path(TEMP_DATA.name))
app.state.settings = AppSettings(
    gateway_enabled=False,
    location_name="Host verification",
    latitude=39.7392,
    longitude=-104.9903,
    use_ip_location=False,
    timezone="America/Denver",
)
app.state.data_logger = BrowserTestLogger()
app.state.poller = BrowserTestPoller()
app.state.forecast_service = BrowserTestForecast()
app.state.csrf_token = "playwright-test-token"
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount(
    "/theme-assets",
    StaticFiles(directory=str(app.state.theme_manager.assets_dir), check_dir=False),
    name="theme-assets",
)
register_routes(app)


if __name__ == "__main__":
    port = int(os.environ.get("CAELUS_PLAYWRIGHT_PORT", "8768"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
