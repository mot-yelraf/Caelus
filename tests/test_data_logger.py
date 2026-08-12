import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from caelus.data_logger import DataLogger


def test_export_readings_filters_by_elapsed_days(tmp_path) -> None:
    logger = DataLogger(str(tmp_path / "caelus.db"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    logger.log_reading(now - timedelta(hours=12), {"temperature": 72.0})
    logger.log_reading(now - timedelta(days=2), {"temperature": 60.0})

    rows = json.loads(logger.export_readings(1, "json"))

    assert [row["temperature"] for row in rows] == [72.0]


def test_csv_export_uses_csv_escaping(tmp_path) -> None:
    logger = DataLogger(str(tmp_path / "caelus.db"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    logger.log_reading(now, {"temperature": "=unexpected,value"})

    rows = list(csv.reader(io.StringIO(logger.export_readings(1, "csv"))))

    assert rows[1][6] == "=unexpected,value"


def test_existing_database_is_additively_migrated_for_7_in_1_metrics(tmp_path) -> None:
    db_path = tmp_path / "caelus.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """CREATE TABLE readings (
            timestamp TEXT PRIMARY KEY, wind_speed REAL, wind_dir INTEGER,
            wind_gust REAL, rain_rate REAL, rain_total REAL, temperature REAL,
            humidity REAL, uv REAL, solar_radiation REAL, pressure REAL,
            indoor_temperature REAL, indoor_humidity REAL
        )"""
    )
    connection.commit()
    connection.close()

    logger = DataLogger(str(db_path))
    logger.log_reading(
        datetime.now(timezone.utc).replace(tzinfo=None),
        {
            "temperature": 68.0,
            "dew_point": 50.0,
            "rain_increment": 0.05,
            "rain_year": 12.5,
            "light_intensity": 12000.0,
        },
    )

    latest = logger.get_latest()
    assert latest["dew_point"] == 50.0
    assert latest["rain_increment"] == 0.05
    assert latest["rain_year"] == 12.5
    assert latest["light_intensity"] == 12000.0


def test_readings_since_returns_elapsed_window_in_chronological_order(tmp_path) -> None:
    logger = DataLogger(str(tmp_path / "caelus.db"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    logger.log_reading(now - timedelta(hours=25), {"temperature": 50.0})
    logger.log_reading(now - timedelta(hours=1), {"temperature": 70.0})
    logger.log_reading(now - timedelta(hours=2), {"temperature": 65.0})

    rows = logger.get_readings_since(now - timedelta(hours=24))

    assert [row["temperature"] for row in rows] == [65.0, 70.0]
