from caelus.metrics import build_24_hour_metric_cards, metric_display_options


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
