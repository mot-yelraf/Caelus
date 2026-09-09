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
AppSettings.settings_path = Path(TEMP_DATA.name) / "settings.json"


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
            "ok": True,
            "provider": settings.forecast_provider,
            "provider_label": settings.forecast_provider,
            "condition": "Clear", "icon": "☀️", "stale": False,
            "high_f": 88, "low_f": 64, "high_c": 31, "low_c": 18,
            "precip_probability": 44, "precip_label": "Rain chance",
            "hours": [
                {"label": f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}",
                 "icon": "☀️", "temperature_f": 66 + hour % 12,
                 "precip_probability": 4, "precip_label": "Rain chance"}
                for hour in range(24)
            ],
            "days": [
                {"date": f"2026-09-{10 + day}", "label": f"{weekday} Sep {10 + day}",
                 "icon": "☀️", "summary": "Mostly clear early",
                 "high_f": 88, "low_f": 64, "high_c": 31, "low_c": 18,
                 "humidity_low": 30, "humidity_high": 85,
                 "wind_low_mph": 0, "wind_high_mph": 12, "wind_descriptor": "light",
                 "precip_probability": 32, "precip_label": "Rain chance"}
                for day, weekday in enumerate(("Thu", "Fri", "Sat", "Sun", "Mon", "Tue"))
            ],
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
