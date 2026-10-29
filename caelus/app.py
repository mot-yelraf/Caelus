import asyncio
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from caelus.settings import AppSettings
from caelus.theme_manager import ThemeManager
from caelus.data_logger import DataLogger
from caelus.adapters import EcowittAdapter
from caelus.observations import WeatherAdapter
from caelus.station import EcowittStationSetup
from caelus.stations import build_stations, start_station, stop_stations
from caelus.forecast import ForecastService
from caelus.weather_climate import WeatherClimateService
from caelus.location import resolve_ip_location
from caelus.poller import GatewayPoller
from caelus.routes import register_routes

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


async def _initialize_optional_services(app: FastAPI) -> None:
    """Warm optional services without preventing gateway polling or the UI."""
    try:
        await asyncio.to_thread(app.state.forecast_service.get, app.state.settings)
    except Exception:
        logger.exception("Startup forecast failed; later requests will retry")
    try:
        app.state.weather_climate_service.snapshot(app.state.settings)
    except Exception:
        logger.exception("Startup weather climate failed; later requests will retry")


def create_app(*, weather_adapter: WeatherAdapter | None = None) -> FastAPI:
    """Wire shared services, optionally injecting a normalized weather adapter."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = []
        initialization = None
        try:
            if getattr(app.state, "stations", None):
                for runtime in app.state.stations.values():
                    # The alias remains replaceable by embedders and lifecycle tests.
                    if runtime.key == app.state.settings.weather_adapter:
                        runtime.poller = app.state.poller
                    await start_station(runtime)
                    started.append(runtime)
            else:
                await app.state.poller.start()
            # Resolve coordinates before serving settings mutations or warming
            # location-dependent services. Provider requests already have timeouts.
            if app.state.settings.use_ip_location:
                try:
                    await asyncio.to_thread(resolve_ip_location, app.state.settings)
                except Exception:
                    logger.exception("Startup location lookup failed; retaining configured location")
            initialization = asyncio.create_task(_initialize_optional_services(app))
            yield
        finally:
            # Finish in-flight settings work before releasing shared services.
            try:
                if initialization is not None:
                    await initialization
            finally:
                try:
                    await app.state.weather_climate_service.close()
                finally:
                    if started:
                        await stop_stations(started)
                    else:
                        await app.state.poller.stop()

    app = FastAPI(title="Caelus", lifespan=lifespan)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR.parent / "templates"))
    app.state.theme_manager = ThemeManager(BASE_DIR.parent / "data")
    app.state.settings = AppSettings.load(app.state.theme_manager)
    app.state.db_path = BASE_DIR.parent / "data" / "caelus.db"
    app.state.db_path.parent.mkdir(parents=True, exist_ok=True)
    app.state.data_logger = DataLogger(str(app.state.db_path))
    app.state.station_lock = threading.RLock()
    app.state.stations = {}
    app.state.station_setup = None
    if weather_adapter is None:
        app.state.stations = build_stations(app, BASE_DIR.parent / "data")
        selected = app.state.stations[app.state.settings.weather_adapter]
        app.state.weather_adapter = selected.adapter
        app.state.data_logger = selected.data_logger
        app.state.poller = selected.poller
        ecowitt = app.state.stations["ecowitt"].adapter
        app.state.gateway = ecowitt.gateway
        app.state.station_setup = EcowittStationSetup(app.state.settings, ecowitt.gateway, app.state.station_lock)
    else:
        app.state.weather_adapter = weather_adapter
        if isinstance(weather_adapter, EcowittAdapter):
            app.state.gateway = weather_adapter.gateway
            app.state.station_setup = EcowittStationSetup(app.state.settings, weather_adapter.gateway, app.state.station_lock)
        app.state.poller = GatewayPoller(app)
    app.state.forecast_service = ForecastService(BASE_DIR.parent / "data" / "forecast.json")
    app.state.weather_climate_service = WeatherClimateService(BASE_DIR.parent / "data" / "weather_climate.json")
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")
    app.mount(
        "/theme-assets",
        StaticFiles(directory=str(app.state.theme_manager.assets_dir), check_dir=False),
        name="theme-assets",
    )
    register_routes(app)

    return app
