from datetime import datetime, timezone
from types import SimpleNamespace

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
