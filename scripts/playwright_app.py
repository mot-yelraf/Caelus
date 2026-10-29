"""Serve deterministic Caelus data for the host-side Playwright gate."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from caelus.routes import register_routes
from caelus.observations import ChannelCapability
from caelus.station import EcowittStationSetup
from caelus.stations import StationRuntime, StationSettings
from caelus.settings import AppSettings
from caelus.theme_manager import ThemeManager


ROOT = Path(__file__).resolve().parents[1]
TEMP_DATA = TemporaryDirectory(prefix="caelus-playwright-")
AppSettings.settings_path = Path(TEMP_DATA.name) / "settings.json"


class BrowserTestLogger:
    """Provide stable readings without creating or querying SQLite state."""

    def __init__(self, temperature=72.5):
        self.temperature = temperature

    def get_latest(self):
        return {
            "timestamp": "2026-08-19T18:00:00",
            "temperature": self.temperature,
            "humidity": 48,
            "pressure": 1013.2,
            "indoor_absolute_pressure": 29.9,
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
            "summary": "Clear early, partly cloudy late",
            "synopsis": "Overnight (NWS · original units): Mostly clear, with a low around 64. Northwest wind around 8 mph.",
            "humidity_low": 30, "humidity_high": 85, "wind_low_mph": 0, "wind_high_mph": 12,
            "condition": "Clear", "icon_key": "sunny", "stale": False,
            "high_f": 88, "low_f": 64, "high_c": 31, "low_c": 18,
            "precip_probability": 44, "precip_label": "Rain chance",
            "hours": [
                {"label": f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}",
                 "icon_key": "sunny", "condition": "Clear", "temperature_f": 66 + hour % 12, "feels_like_f": 38.4, "wind_chill_f": 6.2, "humidity": 48, "wind_mph": 8,
                 "precip_probability": 4, "precip_label": "Rain chance"}
                for hour in range(24)
            ],
            "days": [
                {"date": f"2026-09-{10 + day}", "label": f"{weekday} Sep {10 + day}",
                 "icon_key": "sunny", "condition": "Clear", "summary": "Mostly clear early",
                 "high_f": 88, "low_f": 64, "high_c": 31, "low_c": 18,
                 "humidity_low": 30, "humidity_high": 85,
                 "feels_like_low_f": 0, "feels_like_high_f": 38.4,
                 "feels_like_low_c": -17.8, "feels_like_high_c": 3.6,
                 "wind_chill_low_f": -10, "wind_chill_high_f": 6.2,
                 "wind_chill_low_c": -23.3, "wind_chill_high_c": -14.3,
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

    def __init__(self, settings, key):
        self.settings = StationSettings(settings, key)

    def poll_once(self):
        return None

    def reset_schedule(self):
        return None


class BrowserTestAdapter:
    def __init__(self, settings, key):
        self.settings, self.key = settings, key

    def read(self):
        return None

    def capabilities(self):
        return (ChannelCapability("primary", ("temperature",)),)

    def reset(self):
        return None

    def status(self):
        enabled = self.settings.gateway_enabled if self.key == "ecowitt" else getattr(self.settings, f"{'davis' if self.key == 'davis_vue' else self.key.removesuffix('_usb')}_enabled")
        return {"source_id": self.key, "enabled": enabled, "connected": enabled,
                "state": "online" if enabled else "disabled", "observation_fresh": enabled,
                "station": {"reporting": enabled, "battery_status": "UNKNOWN"}, "sensors": []}


class BrowserTestGateway:
    def discover(self, url):
        return {"ok": True, "gateway_url": url, "gateway_id": "ecowitt-test",
                "gateway_model": "GW3000 test fixture", "inventory": [], "rain_source": "traditional",
                "rain_reset_hour": 0, "live_metric_count": 1}


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
app.state.poller = BrowserTestPoller(app.state.settings, "ecowitt")
app.state.station_lock = RLock()
app.state.stations = {
    key: StationRuntime(key, name, BrowserTestAdapter(app.state.settings, key), logger, poller)
    for key, name, logger, poller in (
        ("ecowitt", "Ecowitt", app.state.data_logger, app.state.poller),
        ("acurite_usb", "AcuRite", BrowserTestLogger(55.0), BrowserTestPoller(app.state.settings, "acurite_usb")),
        ("wmr100_usb", "Oregon Scientific", BrowserTestLogger(58.1), BrowserTestPoller(app.state.settings, "wmr100_usb")),
        ("davis_vue", "Davis Vantage Vue", BrowserTestLogger(64.2), BrowserTestPoller(app.state.settings, "davis_vue")),
    )
}
app.state.weather_adapter = app.state.stations["ecowitt"].adapter
app.state.station_setup = EcowittStationSetup(app.state.settings, BrowserTestGateway(), app.state.station_lock)
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
