from caelus.location import resolve_ip_location
from caelus.settings import AppSettings


class FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self):
        return {
            "latitude": 32.79,
            "longitude": -108.2749,
            "timezone": "America/Denver",
            "city": "Silver City",
            "region": "New Mexico",
        }


class FakeSession:
    def __init__(self) -> None:
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_ip_location_fills_and_persists_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    settings = AppSettings()
    session = FakeSession()

    result = resolve_ip_location(settings, force=True, session=session)

    assert result["ok"] is True
    assert settings.latitude == 32.79
    assert settings.longitude == -108.2749
    assert settings.timezone == "America/Denver"
    assert settings.location_name == "Silver City, New Mexico"
    assert settings.location_source == "ip"
    assert settings.location_provider == "ipapi.co"
    assert AppSettings.load().latitude == 32.79
    assert session.calls[0][0] == "https://ipapi.co/json/"


def test_existing_coordinates_skip_network_without_force() -> None:
    settings = AppSettings(latitude=40.0, longitude=-105.0, location_source="manual")
    session = FakeSession()

    result = resolve_ip_location(settings, session=session, persist=False)

    assert result["ok"] is True
    assert result["source"] == "manual"
    assert session.calls == []
