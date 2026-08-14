from caelus.metrics import build_24_hour_metric_cards


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


def test_gateway_pressure_cards_display_hpa_without_changing_stored_units() -> None:
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
    assert relative["label"] == "Gateway relative pressure"
    assert relative["unit"] == "hPa"
    assert relative["current"] == 1006.0
    assert absolute["label"] == "Gateway absolute pressure"
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
