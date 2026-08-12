import pytest

from caelus.gateway import (
    EcowittGateway,
    EcowittGatewayError,
    normalize_ecowitt_livedata,
    normalize_gateway_base_url,
    normalize_sensor_inventory,
    normalized_gateway_id,
)
from caelus.settings import AppSettings


def test_metric_and_imperial_7_in_1_payloads_normalize_identically() -> None:
    metric = {
        "common_list": [
            {"id": "0x02", "val": "20.0", "unit": "C"},
            {"id": "0x03", "val": "10.0 C"},
            {"id": "0x04", "val": "19.0 C"},
            {"id": "0x07", "val": "65%"},
            {"id": "0x09", "val": "1013.2 hPa"},
            {"id": "0x0A", "val": "0"},
            {"id": "0x0B", "val": "4.4704 m/s"},
            {"id": "0x0C", "val": "8.9408 m/s"},
            {"id": "0x15", "val": "350 W/m2"},
            {"id": "0x17", "val": "3"},
        ],
        "rain": [
            {"id": "0x0E", "val": "25.4 mm/Hr"},
            {"id": "0x10", "val": "50.8 mm"},
            {"id": "0x11", "val": "76.2 mm"},
        ],
    }
    imperial = {
        "common_list": [
            {"id": "0x02", "val": "68.0", "unit": "F"},
            {"id": "0x03", "val": "50.0 F"},
            {"id": "0x04", "val": "66.2 F"},
            {"id": "0x07", "val": "65%"},
            {"id": "0x09", "val": "29.919 inHg"},
            {"id": "0x0A", "val": "0"},
            {"id": "0x0B", "val": "10 mph"},
            {"id": "0x0C", "val": "20 mph"},
            {"id": "0x15", "val": "350 W/m2"},
            {"id": "0x17", "val": "3"},
        ],
        "rain": [
            {"id": "0x0E", "val": "1 in/Hr"},
            {"id": "0x10", "val": "2 in"},
            {"id": "0x11", "val": "3 in"},
        ],
    }

    metric_values = normalize_ecowitt_livedata(metric)
    imperial_values = normalize_ecowitt_livedata(imperial)

    for name in (
        "temperature", "dew_point", "wind_chill", "humidity", "pressure",
        "wind_dir", "wind_speed", "wind_gust", "solar_radiation", "uv",
        "rain_rate", "rain_total", "rain_week",
    ):
        assert metric_values[name] == pytest.approx(imperial_values[name], abs=0.01)
    assert metric_values["wind_dir"] == 0


def test_lux_is_not_mislabeled_and_malformed_values_are_ignored() -> None:
    values = normalize_ecowitt_livedata(
        {
            "common_list": [
                {"id": "0x15", "val": "12000 lux"},
                {"id": "0x02", "val": "bad", "unit": "C"},
                {"id": "0x99", "val": "123"},
            ]
        }
    )

    assert values == {"light_intensity": 12000.0}


def test_inventory_and_stable_gateway_identity_follow_ecowitt_contract() -> None:
    inventory = normalize_sensor_inventory(
        [
            [
                {"img": "wh69", "type": "0", "name": "7-in-1", "id": "E8", "signal": "3"},
                {"img": "wh31", "type": "6", "id": "FFFFFFFF", "signal": "0"},
                {"img": "wh25", "type": "4", "id": "1234", "signal": "4", "idst": "0"},
            ],
            [{"img": "wh51", "type": "14", "name": "Unavailable", "id": "C4BC", "signal": "0"}],
        ]
    )

    assert [sensor["id"] for sensor in inventory] == ["E8", "C4BC"]
    assert normalized_gateway_id("E8:DB:84:0F:15:43") == "ecowitt-e8db840f1543"
    assert normalized_gateway_id("e8-db-84-0f-15-43") == "ecowitt-e8db840f1543"


def test_gateway_base_url_rejects_write_or_remote_style_urls() -> None:
    assert normalize_gateway_base_url("http://gw1100.local/") == "http://gw1100.local"
    for value in (
        "https://gw1100.local",
        "http://user:pass@gw1100.local",
        "http://gw1100.local/get_livedata_info",
        "http://gw1100.local?q=1",
    ):
        with pytest.raises(EcowittGatewayError):
            normalize_gateway_base_url(value)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.content = b"{}"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class FakeSession:
    responses = {
        "get_version": {"platform": "ecowitt", "version": "GW1100A_V2.3.1"},
        "get_network_info": {"mac": "E8:DB:84:0F:15:43", "ssid": "private"},
        ("get_sensors_info", 1): [{"img": "wh69", "type": "0", "name": "7-in-1", "id": "E8", "signal": "3"}],
        ("get_sensors_info", 2): [],
        "get_livedata_info": {"common_list": [{"id": "0x02", "val": "68 F"}]},
        "get_rain_totals": {"rainFallPriority": "1", "rstRainDay": "9"},
    }

    @classmethod
    def get(cls, url, params=None, **_kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        key = (endpoint, (params or {}).get("page"))
        return FakeResponse(cls.responses[key] if key in cls.responses else cls.responses[endpoint])


def test_discovery_reads_identity_inventory_and_live_metrics() -> None:
    gateway = EcowittGateway(AppSettings(), session=FakeSession)

    result = gateway.discover("http://gw1100.local")

    assert result["gateway_id"] == "ecowitt-e8db840f1543"
    assert result["inventory"][0]["name"] == "7-in-1"
    assert result["inventory"][0]["reporting"] is True
    assert result["live_metric_count"] == 1
    assert "ssid" not in result
    assert result["rain_reset_hour"] == 9
