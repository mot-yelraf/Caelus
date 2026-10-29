"""Read-only Vue protocol, serial ownership, freshness and rain provenance checks."""

import asyncio
import binascii
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from caelus.davis import (
    DavisError,
    DavisVueAdapter,
    SerialConsole,
    decode_snapshot,
    rain_configuration,
    validate_port,
)
from caelus.settings import AppSettings

FIXTURE = json.loads((Path(__file__).parent / "fixtures/davis-vue.json").read_text())
LOOP = bytes.fromhex(FIXTURE["loop"])
LOOP2 = bytes.fromhex(FIXTURE["loop2"])
CONFIG = bytes.fromhex(FIXTURE["configuration"])


def snapshot(count=101, **kwargs):
    result = decode_snapshot(LOOP, LOOP2, CONFIG, count, "/dev/test-vue")
    return replace(result, **kwargs)


def updated(raw, offset, value, size=2):
    raw = bytearray(raw)
    raw[offset : offset + size] = value.to_bytes(size, "little")
    raw[97:] = binascii.crc_hqx(raw[:97], 0).to_bytes(2, "big")
    return bytes(raw)


class FakeTransport:
    def __init__(self):
        self.current = snapshot()
        self.calls = 0

    def read_snapshot(self):
        self.calls += 1
        return self.current


def adapter():
    return DavisVueAdapter(
        AppSettings(davis_enabled=True, davis_port="/dev/test-vue"), FakeTransport()
    )


def test_vue_fixture_zero_negative_missing_and_unit_semantics():
    data = snapshot()
    values = data.values
    assert values["temperature"] == -12.5
    assert values["humidity"] == values["wind_speed"] == values["wind_dir"] == 0
    assert values["indoor_temperature"] == 72.5 and values["indoor_humidity"] == 45
    assert values["wind_gust"] == 12.3
    assert values["pressure"] == 30.123 and values["absolute_pressure"] == 28.1
    assert values["rain_total"] == pytest.approx(2 / 25.4)
    assert values["rain_month"] == pytest.approx(20 / 25.4)
    assert values["rain_year"] == pytest.approx(200 / 25.4)
    assert values["rain_rate"] == pytest.approx(1 / 25.4)
    assert values["rain_event"] == pytest.approx(2.4 / 25.4)
    assert data.transmitter == 3 and data.battery == "LOW"
    bad = LOOP2
    for offset, value, size in (
        (12, 32767, 2),
        (9, 32767, 2),
        (33, 255, 1),
        (11, 255, 1),
        (14, 255, 1),
        (16, 0, 2),
        (22, 32767, 2),
        (41, 65535, 2),
        (50, 65535, 2),
        (7, 0, 2),
        (67, 65535, 2),
    ):
        bad = updated(bad, offset, value, size)
    values = decode_snapshot(LOOP, bad, CONFIG, 1, "port").values
    assert all(
        values[k] is None
        for k in (
            "temperature",
            "indoor_temperature",
            "humidity",
            "indoor_humidity",
            "wind_speed",
            "wind_dir",
            "wind_gust",
            "rain_rate",
            "rain_total",
            "pressure",
            "absolute_pressure",
        )
    )


@pytest.mark.parametrize("code,scale", [(0, 0.01), (1, 0.2 / 25.4), (2, 0.1 / 25.4)])
def test_rain_bucket_read_from_console_configuration(code, scale):
    config = bytearray(CONFIG)
    config[20] = code << 4
    assert rain_configuration(config) == (3, scale)


def test_invalid_framing_crc_configuration_and_wrong_packet_types():
    assert binascii.crc_hqx(b"123456789", 0) == 0x31C3
    for bad in (LOOP[:-1], b"bad" + LOOP[3:], LOOP[:-1] + b"\x00", LOOP2):
        with pytest.raises(DavisError):
            decode_snapshot(bad, LOOP2, CONFIG, 1, "port")
    for offset, value in ((0, 0), (0, 3), (6, 4), (20, 0x30)):
        config = bytearray(CONFIG)
        config[offset] = value
        with pytest.raises(DavisError):
            rain_configuration(config)


class FakeSerial:
    def __init__(
        self,
        *,
        station_type=17,
        corrupt_config=False,
        broken_loop=False,
        fail_write=False,
    ):
        self.commands = []
        self.pending = b""
        self.closed = False
        self.station_type, self.corrupt_config = station_type, corrupt_config
        self.broken_loop, self.fail_write = broken_loop, fail_write

    def reset_input_buffer(self):
        self.pending = b""

    def write(self, data):
        self.commands.append(data)
        if self.fail_write:
            return 0
        config_crc = binascii.crc_hqx(CONFIG, 0).to_bytes(2, "big")
        if self.corrupt_config:
            config_crc = b"\x00\x00"
        self.pending = {
            b"\n": b"\n\r",
            b"WRD\x12M\n": b"\x06" + bytes([self.station_type]),
            b"EEBRD 17 15\n": b"\x06" + CONFIG + config_crc,
            b"RXCHECK\n": b"\n\rOK\n\r 101 15 0 100 0\n\r",
            b"LPS 3 2\n": b"\x06" + LOOP + (LOOP if self.broken_loop else LOOP2),
        }[data]
        return len(data)

    def read(self, count):
        # Deliberately split all responses, including ACKs, binary data and CRCs.
        chunk, self.pending = (
            self.pending[: min(count, 5)],
            self.pending[min(count, 5) :],
        )
        return chunk

    def close(self):
        self.closed = True


def serial_console(handle):
    def create(**kwargs):
        assert kwargs["timeout"] == 0.25 and kwargs["write_timeout"] == 0.5
        assert kwargs["baudrate"] == 19200
        assert (
            kwargs["bytesize"] == 8
            and kwargs["parity"] == "N"
            and kwargs["stopbits"] == 1
        )
        return handle

    return SerialConsole("/dev/test-vue", serial_module=SimpleNamespace(Serial=create))


def test_serial_session_reads_only_allowlisted_commands_and_always_closes():
    handle = FakeSerial()
    result = serial_console(handle).read_snapshot()
    assert result == snapshot()
    assert handle.closed
    assert handle.commands == [
        b"\n",
        b"WRD\x12M\n",
        b"EEBRD 17 15\n",
        b"RXCHECK\n",
        b"LPS 3 2\n",
    ]


@pytest.mark.parametrize(
    "options",
    [
        {"station_type": 16},
        {"corrupt_config": True},
        {"broken_loop": True},
        {"fail_write": True},
    ],
)
def test_serial_errors_close_port(options):
    handle = FakeSerial(**options)
    with pytest.raises(DavisError):
        serial_console(handle).read_snapshot()
    assert handle.closed


def test_serial_silent_console_is_bounded_and_closes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("caelus.davis.monotonic", lambda: clock[0])
    handle = FakeSerial()

    def read(count):
        clock[0] += 0.25
        return b""

    handle.read = read
    with pytest.raises(DavisError, match="timed out"):
        serial_console(handle).read_snapshot()
    assert clock[0] < 5
    assert handle.commands == [b"\n"] * 3
    assert handle.closed


@pytest.mark.parametrize(
    "value",
    [
        "socket://host:1234",
        "http://host",
        "relative",
        "/dev/../etc/passwd",
        "COM0",
        "COM1\n",
        True,
    ],
)
def test_port_rejects_urls_relative_paths_and_control_characters(value):
    with pytest.raises(ValueError):
        validate_port(value)


def test_reception_progress_stale_rf_recovery_and_source_changes(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("caelus.davis.monotonic", lambda: clock[0])
    device = adapter()
    device.sample_once()
    assert device.status()["connected"] and not device.status()["observation_fresh"]
    assert "temperature" not in device.read().measurements
    assert device.read() is None
    device.transport.current = snapshot(104)
    device.sample_once()
    assert device.read().measurements["temperature"] == -12.5
    assert device.status()["station"] == {"reporting": True, "battery_status": "LOW"}
    clock[0] += 121
    device.sample_once()  # USB still works; RF count stopped progressing.
    assert device.status()["connected"] and not device.status()["observation_fresh"]
    values = device.read().measurements
    assert "temperature" not in values and "rain_total" not in values
    assert values["pressure"] == 30.123
    device.transport.current = snapshot(105)
    device.sample_once()
    assert device.status()["observation_fresh"]
    device.transport.current = snapshot(106, identity="replacement")
    device.sample_once()
    assert not device.status()[
        "observation_fresh"
    ]  # New source needs its own RF baseline.
    device.transport.current = snapshot(107, identity="replacement")
    device.sample_once()
    assert device.status()["observation_fresh"]
    device.transport.current = snapshot(0, identity="replacement")
    device.sample_once()
    assert not device.status()[
        "observation_fresh"
    ]  # Midnight or console diagnostic reset.


def test_disabled_connection_changes_and_transport_errors_clear_cache():
    device = adapter()
    device.settings.davis_enabled = False
    device.sample_once()
    assert device.transport.calls == 0 and device.read() is None
    device.settings.davis_enabled = True
    device.sample_once()
    device.settings.davis_port = "/dev/other"
    assert device.read() is None and not device.status()["connected"]

    def fail():
        raise DavisError("unplugged")

    device.transport.read_snapshot = fail
    device.sample_once()
    assert device.status()["last_error"] == "unplugged"
    assert not device.status()["connected"] and device.read() is None


def test_daily_rain_persistence_restart_and_bucket_provenance(tmp_path):
    from caelus.data_logger import DataLogger
    from caelus.poller import GatewayPoller

    device = adapter()
    data = DataLogger(str(tmp_path / "davis.db"))
    poller = GatewayPoller(
        SimpleNamespace(
            state=SimpleNamespace(
                settings=device.settings, weather_adapter=device, data_logger=data
            )
        )
    )
    device.sample_once()
    device.transport.current = snapshot(102)
    device.sample_once()
    first = poller.poll_once()
    assert first.get("rain_increment") is None
    device.transport.current = replace(
        snapshot(103), values={**snapshot().values, "rain_total": 3 / 25.4}
    )
    device.sample_once()
    second = poller.poll_once()
    assert second["rain_increment"] == pytest.approx(round(1 / 25.4, 3))
    assert second["rain_total"] == pytest.approx(3 / 25.4)
    # A new adapter can use the SQLite baseline after radio freshness is verified.
    restarted = DavisVueAdapter(device.settings, FakeTransport())
    restarted.sample_once()
    restarted.transport.current = replace(
        snapshot(104), values={**snapshot().values, "rain_total": 4 / 25.4}
    )
    restarted.sample_once()
    poller.adapter = restarted
    assert poller.poll_once()["rain_increment"] == pytest.approx(round(1 / 25.4, 3))
    restarted.transport.current = replace(snapshot(105), rain_scale=0.01)
    restarted.sample_once()
    assert poller.poll_once().get("rain_increment") is None
    # Daily reset uses the configured timezone and the new day's total.
    prior = data.get_latest()
    at = datetime.fromisoformat(prior["timestamp"]).replace(
        tzinfo=timezone.utc
    ) + timedelta(days=1)
    from caelus.observations import Observation, RainPolicy
    from caelus.rain import process_rain, counter_identity

    observation = Observation(
        source_id=prior["source_id"],
        observed_at=at,
        received_at=at,
        measurements={"rain_total": 0.02},
        rain=RainPolicy(kind="daily"),
    )
    prior["rain_counter_id"] = counter_identity(observation.source_id, observation.rain)
    process_rain(observation, prior)
    assert observation.measurements["rain_increment"] == 0.02


def test_sampler_lifecycle_and_status_do_not_touch_transport():
    device = adapter()
    device.settings.davis_enabled = False

    async def exercise():
        await device.start()
        task = device.task
        await device.start()
        assert device.task is task
        await asyncio.sleep(0.01)
        await asyncio.wait_for(device.stop(), 1)
        assert task.done()

    asyncio.run(exercise())
    device.status()
    device.capabilities()
    assert device.transport.calls == 0


def test_invalid_davis_fields_load_individually(tmp_path, monkeypatch, caplog):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(AppSettings, "settings_path", path)
    path.write_text(
        json.dumps(
            {
                "davis_enabled": True,
                "davis_port": "socket://host:1234",
                "davis_baud_rate": True,
                "davis_poll_interval_seconds": 120,
                "weather_adapter": "davis_vue",
                "latitude": 40,
            }
        )
    )
    settings = AppSettings.load()
    assert settings.davis_enabled and settings.latitude == 40
    assert settings.davis_port == "" and settings.davis_baud_rate == 19200
    assert (
        settings.davis_poll_interval_seconds == 120
        and settings.weather_adapter == "davis_vue"
    )
    assert "Ignoring invalid setting davis_port" in caplog.text
    assert "Ignoring invalid setting davis_baud_rate" in caplog.text
