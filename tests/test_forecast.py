import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import caelus.forecast as forecast_module
from caelus.forecast import (
    MET_URL,
    ForecastService,
    build_decisions,
    build_forecast,
    normalize_forecast_provider,
    normalize_met,
    normalize_nws,
    normalize_open_meteo,
)
from caelus.settings import AppSettings


def future_local_times(count: int) -> list[str]:
    start = datetime.now(ZoneInfo("America/Denver")).replace(minute=0, second=0, microsecond=0)
    return [(start + timedelta(hours=index)).replace(tzinfo=None).isoformat() for index in range(count)]


def test_provider_names_are_normalized() -> None:
    assert normalize_forecast_provider("MET Norway") == "met_no"
    assert normalize_forecast_provider("Open-Meteo") == "open_meteo"
    assert normalize_forecast_provider("NWS") == "us"
    assert MET_URL.endswith("/complete")


def test_open_meteo_builds_today_forecast_and_decisions() -> None:
    times = future_local_times(24)
    payload = {
        "hourly": {
            "time": times,
            "temperature_2m": [60 + index for index in range(24)],
            "precipitation_probability": [70] * 24,
            "precipitation": [0.2] * 24,
            "weather_code": [61] * 24,
            "wind_speed_10m": [8] * 24,
        }
    }

    rows = normalize_open_meteo(payload, "America/Denver")
    forecast = build_forecast("open_meteo", rows, "America/Denver")
    decisions = build_decisions(forecast)

    assert forecast["ok"] is True
    assert forecast["condition"] == "Rain"
    assert forecast["precip_label"] == "Rain chance"
    assert len(forecast["hours"]) == 24
    assert [hour["label"] for hour in forecast["hours"]] == [hour["label"] for hour in rows[:24]]
    assert forecast["hours"][0]["precip_label"] == "Rain chance"
    assert decisions[0]["status"] == "Delay watering"
    assert all(hour["duration_hours"] == 1.0 for hour in forecast["hours"])


def test_open_meteo_builds_six_future_daily_forecasts() -> None:
    times = future_local_times(7 * 24)
    payload = {
        "hourly": {
            "time": times,
            "temperature_2m": [55 + index % 24 for index in range(len(times))],
            "precipitation_probability": [10 + index % 4 * 10 for index in range(len(times))],
            "precipitation": [0.1] * len(times),
            "weather_code": [2] * len(times),
            "relative_humidity_2m": [30 + index % 40 for index in range(len(times))],
            "cloud_cover": [55] * len(times),
            "wind_speed_10m": [7] * len(times),
        }
    }

    forecast = build_forecast(
        "open_meteo", normalize_open_meteo(payload, "America/Denver"), "America/Denver"
    )

    assert len(forecast["days"]) == 6
    assert forecast["days"][0]["label"] == (
        datetime.now(ZoneInfo("America/Denver")) + timedelta(days=1)
    ).strftime("%a %b %d").replace(" 0", " ")
    assert all(day["high_f"] >= day["low_f"] for day in forecast["days"])
    assert all(day["condition"] == "Partly cloudy" for day in forecast["days"])
    assert forecast["days"][0]["humidity_low"] is not None
    assert forecast["days"][0]["humidity_high"] is not None
    assert forecast["days"][0]["wind_descriptor"] == "light/moderate"
    assert forecast["days"][0]["precip_label"] == "Rain chance"
    assert "rain/showers" in forecast["days"][0]["summary"]


def test_snow_forecast_uses_snow_chance_labels() -> None:
    times = future_local_times(48)
    payload = {
        "hourly": {
            "time": times,
            "temperature_2m": [28] * len(times),
            "precipitation_probability": [65] * len(times),
            "precipitation": [0.4] * len(times),
            "weather_code": [71] * len(times),
            "wind_speed_10m": [5] * len(times),
        }
    }

    forecast = build_forecast(
        "open_meteo",
        normalize_open_meteo(payload, "America/Denver"),
        "America/Denver",
    )

    assert forecast["precip_label"] == "Snow chance"
    assert "snow/sleet" in forecast["summary"]
    assert "rain/showers" not in forecast["summary"]
    assert forecast["hours"][0]["precip_label"] == "Snow chance"
    assert forecast["days"][0]["precip_label"] == "Snow chance"


def test_hour_labels_use_twelve_hour_clock() -> None:
    payload = {
        "hourly": {
            "time": ["2026-08-12T00:00", "2026-08-12T13:00"],
            "temperature_2m": [60, 70],
            "weather_code": [0, 0],
        }
    }

    rows = normalize_open_meteo(payload, "America/Denver")

    assert [row["label"] for row in rows] == ["12 AM", "1 PM"]


def test_met_and_nws_payloads_share_hourly_contract() -> None:
    future = datetime.now(ZoneInfo("America/Denver")).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    met_payload = {
        "properties": {
            "timeseries": [
                {
                    "time": future.astimezone(ZoneInfo("UTC")).isoformat(),
                    "data": {
                        "instant": {"details": {"air_temperature": 20, "wind_speed": 3}},
                        "next_1_hours": {
                            "summary": {"symbol_code": "partlycloudy_day"},
                            "details": {"precipitation_amount": 0},
                        },
                    },
                }
            ]
        }
    }
    nws_payload = {
        "properties": {
            "periods": [
                {
                    "startTime": future.isoformat(),
                    "temperature": 68,
                    "temperatureUnit": "F",
                    "windSpeed": "5 to 10 mph",
                    "shortForecast": "Partly Cloudy",
                    "probabilityOfPrecipitation": {"value": 10},
                }
            ]
        }
    }

    met = normalize_met(met_payload, "America/Denver")[0]
    nws = normalize_nws(nws_payload, "America/Denver")[0]

    assert set(met) == set(nws)
    assert met["temperature_f"] == 68
    assert nws["precip_probability"] == 10


def test_met_uses_six_hour_summary_for_longer_range_rows() -> None:
    future = datetime.now(ZoneInfo("UTC")) + timedelta(days=4)
    payload = {
        "properties": {
            "timeseries": [
                {
                    "time": future.isoformat(),
                    "data": {
                        "instant": {"details": {"air_temperature": 10, "wind_speed": 4}},
                        "next_6_hours": {
                            "summary": {"symbol_code": "heavyrain"},
                            "details": {
                                "precipitation_amount": 5.5,
                                "probability_of_precipitation": 92,
                            },
                        },
                    },
                }
            ]
        }
    }

    row = normalize_met(payload, "America/Denver")[0]

    assert row["condition"] == "Rain showers"
    assert row["precipitation_mm"] == 5.5
    assert row["precip_probability"] == 92
    assert row["duration_hours"] == 6.0


def test_frost_decision_uses_next_24_hours_across_midnight(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(2026, 9, 3, 18, tzinfo=timezone.utc)
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

    monkeypatch.setattr(forecast_module, "datetime", FixedDateTime)
    rows = [
        {
            "time": time,
            "temperature_f": temperature,
            "condition": "Clear",
            "precip_probability": 0,
            "precipitation_mm": 0,
            "wind_mph": 2,
            "humidity": 50,
            "cloud_percent": 0,
            "duration_hours": 1,
        }
        for time, temperature in (
            ("2026-09-03T18:00:00+00:00", 50),
            ("2026-09-03T21:00:00+00:00", 45),
            ("2026-09-04T02:00:00+00:00", 25),
        )
    ]

    forecast = build_forecast("open_meteo", rows, "UTC")
    frost = build_decisions(forecast)[1]

    assert forecast["low_f"] == 45
    assert forecast["decision_low_f"] == 25
    assert frost["status"] == "Protect tender plants"
    assert frost["detail"] == "Next 24-hour low 25°F."


def test_exact_zero_and_missing_forecast_lows_are_distinct() -> None:
    freezing = build_decisions({"ok": True, "decision_low_f": 0})[1]
    unavailable = build_decisions({"ok": True})[1]

    assert freezing["status"] == "Protect tender plants"
    assert freezing["detail"] == "Next 24-hour low 0°F."
    assert unavailable["status"] == "Forecast unavailable"


def test_outdoor_decision_chooses_a_contiguous_period_with_its_duration() -> None:
    decision = build_decisions(
        {
            "ok": True,
            "low_f": 50,
            "decision_hours": [
                {"time": "2026-09-03T09:00:00+00:00", "duration_hours": 1, "precip_probability": 0, "wind_mph": 2},
                {"time": "2026-09-03T12:00:00+00:00", "duration_hours": 1, "precip_probability": 90, "wind_mph": 2},
                {"time": "2026-09-03T17:00:00+00:00", "duration_hours": 1, "precip_probability": 0, "wind_mph": 2},
            ],
        }
    )[2]

    assert decision["status"].endswith("09:00–10:00")


def test_legacy_cache_is_retained_if_daily_refresh_fails(tmp_path) -> None:
    cache_path = tmp_path / "forecast.json"
    cache_path.write_text(
        json.dumps(
            {
                "ok": True,
                "provider": "met_no",
                "provider_label": "MET Norway",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "latitude": 32.77,
                "longitude": -108.28,
                "hours": [{"label": "Now"}],
            }
        ),
        encoding="utf-8",
    )

    class OfflineSession:
        @staticmethod
        def get(*_args, **_kwargs):
            raise OSError("offline")

    settings = AppSettings(latitude=32.77, longitude=-108.28, forecast_provider="met_no")
    result = ForecastService(cache_path, session=OfflineSession()).get(settings)

    assert result["ok"] is True
    assert result["stale"] is True
    assert result["days"] == []


def test_non_object_cache_is_discarded_instead_of_crashing(tmp_path) -> None:
    cache_path = tmp_path / "forecast.json"
    cache_path.write_text("[]", encoding="utf-8")

    class OfflineSession:
        @staticmethod
        def get(*_args, **_kwargs):
            raise OSError("offline")

    result = ForecastService(cache_path, session=OfflineSession()).get(
        AppSettings(latitude=32.77, longitude=-108.28, forecast_provider="met_no")
    )

    assert result["ok"] is False
    assert result["reason"] == "offline"


def test_today_ranges_headline_and_synopsis_match_hourly_data(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 11, 5, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(forecast_module, "datetime", FixedDateTime)
    rows = normalize_open_meteo({"hourly": {
        "time": [f"2026-09-11T{hour:02d}:00:00+00:00" for hour in range(5, 11)],
        "temperature_2m": [60, 62, 65, 70, 75, 80],
        "relative_humidity_2m": [70, 65, 50, 40, 30, 0],
        "cloud_cover": [0, 0, 20, 40, 55, 55],
        "weather_code": [0, 0, 0, 2, 2, 2],
        "wind_speed_10m": [0, 2, 4, 6, 8, 10],
        "precipitation_probability": [0, 0, 0, 0, 0, 15],
    }}, "UTC")
    result = build_forecast("open_meteo", rows, "UTC")
    assert result["summary"] == "Clear early, partly cloudy late"
    assert result["synopsis"] == "Clear, then partly cloudy around 8 AM."
    assert (result["humidity_low"], result["humidity_high"]) == (0, 70)
    assert (result["wind_low_mph"], result["wind_high_mph"]) == (0, 10)
    assert result["precip_probability"] == 15
    assert rows[-1]["icon"] == "🌤️"
    assert result["cache_format"] == forecast_module.CACHE_FORMAT


def test_nws_narrative_matches_period_and_preserves_original_units():
    rows = normalize_nws({"properties": {"periods": [
        {"startTime": f"2026-09-11T{hour:02d}:00:00+00:00", "temperature": 63,
         "shortForecast": "Mostly clear"}
        for hour in (5, 6, 7)
    ]}}, "UTC")
    forecast_module.attach_nws_narratives(rows, {"properties": {"periods": [
        {"startTime": "2026-09-10T23:00:00-06:00", "endTime": "2026-09-11T01:00:00-06:00",
         "name": "Overnight", "detailedForecast": "Low around 63. Wind 8 mph."},
    ]}})
    assert rows[0]["narrative"] == rows[1]["narrative"] == "Low around 63. Wind 8 mph."
    assert "narrative" not in rows[2]
    assert forecast_module._forecast_synopsis("us", rows) == (
        "Overnight (NWS · original units): Low around 63. Wind 8 mph."
    )


def test_nws_optional_narrative_failure_keeps_hourly_forecast(tmp_path, caplog):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    class Session:
        def get(self, url, **kwargs):
            if "points/" in url:
                return Response({"properties": {"forecastHourly": "https://example.test/hourly",
                                                "forecast": "https://example.test/narrative"}})
            if url.endswith("hourly"):
                return Response({"properties": {"periods": [
                    {"startTime": datetime.now(timezone.utc).isoformat(), "temperature": 63,
                     "shortForecast": "Clear", "relativeHumidity": {"value": 70}}
                ]}})
            raise OSError("narrative offline")

    result = ForecastService(tmp_path / "forecast.json", session=Session()).get(
        AppSettings(latitude=32, longitude=-108, forecast_provider="us")
    )
    assert result["ok"] is True
    assert result["stale"] is False
    assert result["humidity_high"] == 70
    assert result["synopsis"] == "Clear."
    assert "NWS narrative supplement failed" in caplog.text
