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
