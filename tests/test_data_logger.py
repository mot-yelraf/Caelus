import csv
import io
import json
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
