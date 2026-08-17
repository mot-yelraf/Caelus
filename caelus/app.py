import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from caelus.settings import AppSettings
from caelus.data_logger import DataLogger
from caelus.gateway import EcowittGateway
from caelus.forecast import ForecastService
from caelus.location import resolve_ip_location
from caelus.poller import GatewayPoller
from caelus.routes import register_routes

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.settings.use_ip_location:
            await asyncio.to_thread(resolve_ip_location, app.state.settings)
        await asyncio.to_thread(app.state.forecast_service.get, app.state.settings)
        await app.state.poller.start()
        try:
            yield
        finally:
            await app.state.poller.stop()

    app = FastAPI(title="Caelus", lifespan=lifespan)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR.parent / "templates"))
    app.state.settings = AppSettings.load()
    app.state.db_path = BASE_DIR.parent / "data" / "caelus.db"
    app.state.db_path.parent.mkdir(parents=True, exist_ok=True)
    app.state.data_logger = DataLogger(str(app.state.db_path))
    app.state.gateway = EcowittGateway(app.state.settings)
    app.state.poller = GatewayPoller(app)
    app.state.forecast_service = ForecastService(BASE_DIR.parent / "data" / "forecast.json")
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")
    register_routes(app)

    return app
