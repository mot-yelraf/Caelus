from datetime import datetime, timedelta

import pytest

from caelus.metrics import build_24_hour_metric_cards, calculate_outdoor_vpd, metric_display_options


def test_metric_cards_preserve_zero_and_calculate_complete_window_stats() -> None:
    cards = build_24_hour_metric_cards(
        [
            {"timestamp": "2026-08-12T10:00:00", "wind_speed": 0, "uv": None},
            {"timestamp": "2026-08-12T11:00:00", "wind_speed": 3, "uv": None},
            {"timestamp": "2026-08-12T12:00:00", "wind_speed": 6, "uv": None},
        ]
    )

    assert [card["key"] for card in cards] == ["wind_speed"]
    card = cards[0]
    assert card["current"] == 6.0
    assert card["stats"]["min"] == 0.0
    assert card["stats"]["avg"] == 3.0
    assert card["stats"]["max"] == 6.0
    assert len(card["series"]) == 3


def test_metric_card_graph_series_is_bounded_but_stats_use_every_reading() -> None:
    rows = [
        {"timestamp": f"2026-08-12T00:{index % 60:02d}:00", "temperature": index}
        for index in range(600)
    ]

    card = build_24_hour_metric_cards(rows)[0]

    assert len(card["series"]) <= 289
    assert card["series"][0]["value"] == 0.0
    assert card["series"][-1]["value"] == 599.0
    assert card["stats"]["samples"] == 600
    assert card["stats"]["avg"] == 299.5


def test_metric_sampling_preserves_extrema_and_six_hour_stats_are_exact() -> None:
    observed_at = datetime(2026, 8, 13)
    start = observed_at - timedelta(hours=24)
    rows = [
        {
            "timestamp": (start + timedelta(minutes=index)).isoformat(),
            "wind_gust": 100 if index == 1 else (25 if index >= 24 * 60 - 360 else 0),
        }
        for index in range(24 * 60 + 1)
    ]

    card = build_24_hour_metric_cards(rows, observed_at=observed_at)[0]

    assert len(card["series"]) <= 289
    assert max(point["value"] for point in card["series"]) == 100
    assert card["stats_by_hours"]["24"]["max"] == 100.0
    assert card["stats_by_hours"]["6"]["min"] == 25.0
    assert card["stats_by_hours"]["6"]["max"] == 25.0


def test_wind_direction_uses_circular_mean_and_handles_undefined_resultant() -> None:
    north = build_24_hour_metric_cards(
        [
            {"timestamp": "2026-08-12T10:00:00", "wind_dir": 350},
            {"timestamp": "2026-08-12T11:00:00", "wind_dir": 10},
        ]
    )[0]
    undefined = build_24_hour_metric_cards(
        [
            {"timestamp": "2026-08-12T10:00:00", "wind_dir": 90},
            {"timestamp": "2026-08-12T11:00:00", "wind_dir": 270},
        ]
    )[0]

    assert north["stats"]["avg"] == 0.0
    assert north["stats"]["min"] is None
    assert north["stats"]["max"] is None
    assert undefined["stats"]["avg"] is None


def test_metric_cards_pin_primary_row_then_sort_remaining_labels() -> None:
    reading = {
        "timestamp": "2026-08-15T12:00:00",
        "uv": 3,
        "temperature": 72,
        "rain_total": 0.2,
        "pressure": 29.9,
        "humidity": 45,
        "wind_speed": 4,
        "wind_dir": 225,
        "dew_point": 50,
    }

    cards = build_24_hour_metric_cards([reading])

    assert [(card["key"], card["label"]) for card in cards] == [
        ("temperature", "Outdoor temperature"),
        ("humidity", "Outdoor relative humidity"),
        ("wind_dir", "Wind direction"),
        ("rain_total", "Rain today"),
        ("dew_point", "Dew point"),
        ("vpd", "Outdoor VPD"),
        ("pressure", "Relative pressure"),
        ("uv", "UV index"),
        ("wind_speed", "Wind speed"),
    ]


def test_display_style_options_pin_primary_row_then_sort_remaining_labels() -> None:
    options = metric_display_options()

    assert [option.key for option in options[:4]] == [
        "temperature",
        "humidity",
        "wind_dir",
        "rain_total",
    ]
    assert [option.label for option in options[4:]] == sorted(
        (option.label for option in options[4:]), key=str.casefold
    )


@pytest.mark.parametrize("temperature_f, humidity, expected", [
    (77, 50, 1.584),
    (68, 50, 1.169),
    (32, 0, 0.61078),
    (32, 100, 0),
    (14, 90, 0.0286),
    (122, 0, 12.335),
])
def test_outdoor_vpd_matches_sensorius_formula(temperature_f, humidity, expected):
    assert calculate_outdoor_vpd(temperature_f, humidity) == pytest.approx(expected, abs=0.002)


@pytest.mark.parametrize("temperature, humidity", [
    (None, 50), (77, None), (True, 50), (77, False),
    ("invalid", 50), (77, "invalid"), (float("nan"), 50),
    (77, float("inf")), (float("inf"), 50), (77, -1), (77, 101), (-500, 50),
])
def test_outdoor_vpd_rejects_unavailable_or_invalid_inputs(temperature, humidity):
    assert calculate_outdoor_vpd(temperature, humidity) is None


def test_vpd_is_derived_from_each_observation_before_sampling_or_unit_conversion():
    observed = datetime(2026, 10, 19, 12)
    rows = [
        {"timestamp": (observed - timedelta(hours=12)).isoformat(), "temperature": 68, "humidity": 50},
        {"timestamp": (observed - timedelta(hours=2)).isoformat(), "temperature": 77, "humidity": 50},
        {"timestamp": observed.isoformat(), "temperature": 77, "humidity": 100},
    ]
    cards = [next(card for card in build_24_hour_metric_cards(rows, system, observed_at=observed)
                  if card["key"] == "vpd") for system in ("imperial", "metric")]
    assert cards[0] == cards[1]
    card = cards[0]
    assert card["unit"] == "kPa"
    assert card["current"] == 0
    assert card["decimals"] == 3
    assert card["stats"]["samples"] == 3
    assert card["stats"]["min"] == 0
    assert card["stats"]["max"] == pytest.approx(1.584, abs=0.002)
    assert card["stats"]["avg"] == pytest.approx(0.918, abs=0.002)
    assert card["stats_by_hours"]["6"]["samples"] == 2
    assert card["stats_by_hours"]["6"]["avg"] == pytest.approx(0.792, abs=0.002)
    assert "vpd" not in rows[0]


def test_vpd_never_pairs_inputs_from_different_observations():
    rows = [
        {"timestamp": "2026-10-19T10:00:00", "temperature": 77},
        {"timestamp": "2026-10-19T11:00:00", "humidity": 50},
        {"timestamp": "2026-10-19T12:00:00", "temperature": 77, "humidity": 101},
    ]
    assert not any(card["key"] == "vpd" for card in build_24_hour_metric_cards(rows))


def test_vpd_works_with_existing_sqlite_history_without_storing_a_new_column(tmp_path):
    from caelus.data_logger import DataLogger

    logger = DataLogger(str(tmp_path / "history.db"))
    observed = datetime(2026, 10, 19, 12)
    logger.log_reading(observed, {"temperature": 77, "humidity": 50})
    rows = logger.get_readings_since(observed - timedelta(hours=24))
    assert "vpd" not in rows[0]
    card = next(card for card in build_24_hour_metric_cards(rows) if card["key"] == "vpd")
    assert card["current"] == pytest.approx(1.584, abs=0.002)


def test_wind_direction_card_includes_paired_wind_speed_history_and_stats() -> None:
    cards = build_24_hour_metric_cards(
        [
            {
                "timestamp": "2026-08-12T10:00:00",
                "wind_dir": 350,
                "wind_speed": 2,
            },
            {
                "timestamp": "2026-08-12T11:00:00",
                "wind_dir": 10,
                "wind_speed": 6,
            },
            {
                "timestamp": "2026-08-12T12:00:00",
                "wind_dir": None,
                "wind_speed": 4,
            },
        ]
    )

    wind_direction = next(card for card in cards if card["key"] == "wind_dir")

    assert wind_direction["current"] == 10
    assert wind_direction["wind_speed"]["current"] == 4.0
    assert wind_direction["wind_speed"]["stats"]["min"] == 2.0
    assert wind_direction["wind_speed"]["stats"]["avg"] == 4.0
    assert wind_direction["wind_speed"]["stats"]["max"] == 6.0
    assert wind_direction["wind_speed"]["series"] == [
        {
            "timestamp": "2026-08-12T10:00:00",
            "direction": 350,
            "speed": 2.0,
        },
        {
            "timestamp": "2026-08-12T11:00:00",
            "direction": 10,
            "speed": 6.0,
        },
    ]


def test_indoor_pressure_cards_display_hpa_without_changing_stored_units() -> None:
    cards = build_24_hour_metric_cards(
        [
            {
                "timestamp": "2026-08-12T12:00:00",
                "indoor_pressure": 29.708,
                "indoor_absolute_pressure": 24.318,
            }
        ]
    )
    by_key = {card["key"]: card for card in cards}

    relative = by_key["indoor_pressure"]
    absolute = by_key["indoor_absolute_pressure"]
    assert relative["label"] == "Indoor relative pressure"
    assert relative["unit"] == "hPa"
    assert relative["current"] == 1006.0
    assert absolute["label"] == "Indoor absolute pressure"
    assert absolute["unit"] == "hPa"
    assert absolute["current"] == 823.5


def test_metric_preset_converts_temperature_wind_and_rain_to_metric() -> None:
    cards = build_24_hour_metric_cards(
        [
            {
                "timestamp": "2026-08-12T12:00:00",
                "temperature": 68.0,
                "wind_speed": 10.0,
                "rain_total": 1.0,
            }
        ],
        "metric",
        "auto",
    )
    by_key = {card["key"]: card for card in cards}

    assert (by_key["temperature"]["current"], by_key["temperature"]["unit"]) == (20.0, "°C")
    assert (by_key["wind_speed"]["current"], by_key["wind_speed"]["unit"]) == (16.1, "km/h")
    assert (by_key["rain_total"]["current"], by_key["rain_total"]["unit"]) == (25.4, "mm")


def test_rain_metric_cards_never_expose_negative_values() -> None:
    cards = build_24_hour_metric_cards(
        [
            {"timestamp": "2026-08-15T10:00:00", "rain_total": -0.1},
            {"timestamp": "2026-08-15T11:00:00", "rain_total": 0.25},
        ]
    )

    rain = cards[0]
    assert [point["value"] for point in rain["series"]] == [0.0, 0.25]
    assert rain["stats"]["min"] == 0.0


@pytest.mark.parametrize(('temperature', 'humidity', 'wind', 'expected'), [
    (41, 91, 0, 38.51), (41, 91, 0.2, 38.40), (45, 72, 0, 42.14),
    (20, 70, 15, 5.89), (90, 70, 0, 102.75), (0, 0, 0, -7.2),
    (75, 100, 0, 85.36), (85, 90, 0, 99.70),
])
def test_feels_like_uses_apparent_temperature_in_cool_and_hot_weather(temperature, humidity, wind, expected):
    from caelus.metrics import calculate_feels_like

    assert calculate_feels_like(temperature, humidity, wind) == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize(('temperature', 'humidity', 'wind'), [
    (None, 50, 0), (70, None, 0), (70, -1, 0), (70, 101, 0), ('bad', 50, 0),
    (float('nan'), 50, 0), (70, float('inf'), 0), (True, 50, 0),
    (41, 91, None), (41, 91, -1), (41, 91, float('nan')),
    (41, 91, float('inf')), (41, 91, True), (41, 91, 'bad'),
    (-400, 91, 0), (float('1e308'), 91, 0),
])
def test_feels_like_requires_valid_paired_inputs(temperature, humidity, wind):
    from caelus.metrics import calculate_feels_like

    assert calculate_feels_like(temperature, humidity, wind) is None


@pytest.mark.parametrize(('temperature', 'wind', 'expected'), [
    (20, 15, 6.22), (0, 10, -15.93), (50, 4, 48.88),
    (50.1, 10, None), (30, 3, None), (30, 0, None), (30, -1, None),
    (None, 10, None), (30, None, None), ('bad', 10, None),
    (30, float('inf'), None), (False, 10, None),
])
def test_wind_chill_validity_and_reference_values(temperature, wind, expected):
    from caelus.metrics import calculate_wind_chill

    result = calculate_wind_chill(temperature, wind)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize(('temperature', 'humidity', 'expected'), [
    (90, 70, 105.92), (100, 10, 94.12), (85, 90, 101.78),
    (41, 91, None), (79, 100, None), (80, 0, None),
    (None, 70, None), (90, None, None), (90, 101, None),
    (90, -1, None), (float('nan'), 50, None), ('bad', 50, None),
])
def test_locally_derived_heat_index(temperature, humidity, expected):
    from caelus.metrics import calculate_heat_index

    result = calculate_heat_index(temperature, humidity)
    assert result is None if expected is None else result == pytest.approx(expected, abs=0.02)
