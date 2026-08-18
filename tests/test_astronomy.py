import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import caelus.astronomy as astronomy_module
from caelus.astronomy import astronomy_context, moon_phase_context


def test_reference_new_moon_is_identified() -> None:
    moon = moon_phase_context(datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc))

    assert moon["name"] == "New moon"
    assert moon["illumination"] == 0
    assert sum(item["active"] for item in moon["cycle"]) == 1


def test_half_cycle_is_full_moon() -> None:
    moon = moon_phase_context(datetime(2000, 1, 21, 12, 36, tzinfo=timezone.utc))

    assert moon["name"] == "Full moon"
    assert moon["illumination"] == 100


def test_local_moon_orientation_changes_with_observer_location() -> None:
    observed_at = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)
    northern = SimpleNamespace(
        timezone="America/Denver", location_name="Silver City", latitude=32.77, longitude=-108.28
    )
    southern = SimpleNamespace(
        timezone="Etc/GMT+7", location_name="Southern observer", latitude=-32.77, longitude=-108.28
    )

    north_view = astronomy_context(northern, observed_at)
    south_view = astronomy_context(southern, observed_at)

    assert 0 <= north_view["bright_limb_angle"] < 360
    assert abs(north_view["bright_limb_angle"] - south_view["bright_limb_angle"]) > 45
    assert 0 <= north_view["disk_rotation"] < 360
    assert len(north_view["cycle"]) == 8
    assert all("bright_limb_angle" in item for item in north_view["cycle"])
    assert all("disk_rotation" in item for item in north_view["cycle"])
    assert all("representative_date" in item for item in north_view["cycle"])


def test_astronomy_context_includes_local_daylight_duration() -> None:
    settings = SimpleNamespace(
        timezone="America/Denver", location_name="Silver City", latitude=32.77, longitude=-108.28
    )

    result = astronomy_context(settings, datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc))

    assert result["sunrise"] == "06:31"
    assert result["sunset"] == "20:05"
    assert result["daylight_duration"] == "13h 34m"
    assert result["daylight_hours"] == 13.57
    assert result["sunrise_display"] == "6:31 AM"
    assert result["solar_noon_display"].endswith(" PM")
    assert result["sunset_display"] == "8:05 PM"


def test_sunlight_context_includes_poles_season_and_eclipse_contract() -> None:
    settings = SimpleNamespace(
        timezone="America/Denver",
        location_name="Silver City",
        latitude=32.77,
        longitude=-108.28,
    )

    result = astronomy_context(
        settings, datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
    )

    assert result["north_pole_daylight"] == "24h 00m"
    assert result["south_pole_daylight"] == "0h 00m"
    assert result["next_season_label"] == "September Equinox"
    assert result["next_season_date"] == "Sep 22, 2026"
    assert isinstance(result["next_eclipses"], list)
    assert len(result["next_eclipses"]) <= 3


def test_sunlight_context_reports_available_eclipse_details(monkeypatch) -> None:
    settings = SimpleNamespace(
        timezone="America/Denver",
        location_name="Silver City",
        latitude=32.77,
        longitude=-108.28,
    )
    eclipse = {
        "kind": "Partial lunar eclipse",
        "date": "Aug 27, 2026",
        "at": "2026-08-27T22:12:54-06:00",
    }
    monkeypatch.setattr(
        astronomy_module, "_skyfield_runtime_if_installed", lambda: (object(), object())
    )
    monkeypatch.setattr(
        astronomy_module, "_next_visible_eclipses", lambda *_args: [eclipse]
    )

    result = astronomy_context(
        settings, datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    )

    assert result["eclipse_calculation_available"] is True
    assert result["next_eclipses"] == [eclipse]


def test_skyfield_uses_packaged_ephemeris_when_runtime_file_is_missing(
    monkeypatch, tmp_path
) -> None:
    packaged_data = tmp_path / "skyfield-data"
    packaged_data.mkdir()
    ephemeris = packaged_data / "de421.bsp"
    ephemeris.write_bytes(b"test ephemeris")
    fake_package = SimpleNamespace(
        get_skyfield_data_path=lambda: str(packaged_data)
    )
    monkeypatch.setattr(
        astronomy_module, "SKYFIELD_EPHEMERIS_PATH", tmp_path / "missing" / "de421.bsp"
    )
    monkeypatch.setitem(sys.modules, "skyfield_data", fake_package)
    astronomy_module._skyfield_ephemeris_path.cache_clear()

    try:
        assert astronomy_module._skyfield_ephemeris_path() == ephemeris
    finally:
        astronomy_module._skyfield_ephemeris_path.cache_clear()


def test_waxing_and_waning_local_views_have_opposite_light_polarity() -> None:
    settings = SimpleNamespace(
        timezone="America/Denver", location_name="Silver City", latitude=32.77, longitude=-108.28
    )

    result = astronomy_context(settings, datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc))
    waxing_crescent = result["cycle"][1]["bright_limb_angle"]
    waning_crescent = result["cycle"][7]["bright_limb_angle"]
    waxing_quarter = result["cycle"][2]["bright_limb_angle"]
    waning_quarter = result["cycle"][6]["bright_limb_angle"]

    crescent_separation = abs((waxing_crescent - waning_crescent + 180) % 360 - 180)
    quarter_separation = abs((waxing_quarter - waning_quarter + 180) % 360 - 180)
    assert crescent_separation > 120
    assert quarter_separation > 120


def test_lunar_timeline_has_four_previous_and_upcoming_named_events() -> None:
    settings = SimpleNamespace(
        timezone="America/Denver",
        location_name="Silver City",
        latitude=32.77,
        longitude=-108.28,
    )

    result = astronomy_context(
        settings, datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)
    )

    previous = result["previous_phases"]
    upcoming = result["upcoming_phases"]
    assert len(previous) == 4
    assert len(upcoming) == 4
    assert [item["representative_date"] for item in previous] == sorted(
        item["representative_date"] for item in previous
    )
    assert [item["representative_date"] for item in upcoming] == sorted(
        item["representative_date"] for item in upcoming
    )
    assert previous[1]["name"] == "Buck Moon"
    assert all(item["representative_date"] < "2026-08-09" for item in previous)
    assert all(item["representative_date"] > "2026-08-09" for item in upcoming)
    assert all(
        {"date_label", "bright_limb_angle", "disk_rotation"}.issubset(item)
        for item in previous + upcoming
    )
