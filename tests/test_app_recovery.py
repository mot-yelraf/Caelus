import asyncio
import threading
from types import SimpleNamespace

import pytest

from caelus import app as module
from caelus.settings import AppSettings


@pytest.fixture
def app(monkeypatch, tmp_path):
    (tmp_path / 'static').mkdir()
    monkeypatch.setattr(module, 'BASE_DIR', tmp_path / 'caelus')
    monkeypatch.setattr(AppSettings, 'settings_path', tmp_path / 'data/settings.json')
    return module.create_app()


def test_optional_startup_failures_do_not_prevent_polling_or_cleanup(app, monkeypatch):
    calls = []

    async def start():
        calls.append('start')

    async def stop():
        calls.append('stop')

    async def close():
        calls.append('close')
        raise OSError('cleanup failed')

    def fail(*args):
        raise OSError('optional provider unavailable')

    app.state.settings.use_ip_location = True
    app.state.poller = SimpleNamespace(start=start, stop=stop)
    app.state.forecast_service = SimpleNamespace(get=fail)
    app.state.weather_climate_service = SimpleNamespace(snapshot=fail, close=close)
    monkeypatch.setattr(module, 'resolve_ip_location', fail)

    async def exercise():
        with pytest.raises(OSError, match='cleanup failed'):
            async with app.router.lifespan_context(app):
                calls.append('ready')

    asyncio.run(exercise())
    assert calls == ['start', 'ready', 'close', 'stop']


def test_slow_forecast_does_not_block_server_readiness(app):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    async def start():
        calls.append('start')

    async def stop():
        calls.append('stop')

    async def close():
        calls.append('close')

    def forecast(*args):
        entered.set()
        assert release.wait(timeout=2)

    app.state.settings.use_ip_location = False
    app.state.poller = SimpleNamespace(start=start, stop=stop)
    app.state.forecast_service = SimpleNamespace(get=forecast)
    app.state.weather_climate_service = SimpleNamespace(snapshot=lambda *args: None, close=close)

    async def exercise():
        async with app.router.lifespan_context(app):
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                assert calls == ['start']
                assert not release.is_set()
            finally:
                release.set()

    asyncio.run(exercise())
    assert calls == ['start', 'close', 'stop']
