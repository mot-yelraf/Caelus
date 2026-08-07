import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class DataLogger:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    timestamp TEXT PRIMARY KEY,
                    wind_speed REAL,
                    wind_dir INTEGER,
                    wind_gust REAL,
                    rain_rate REAL,
                    rain_total REAL,
                    temperature REAL,
                    humidity REAL,
                    uv REAL,
                    solar_radiation REAL,
                    pressure REAL,
                    indoor_temperature REAL,
                    indoor_humidity REAL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            connection.commit()

    def log_reading(self, timestamp: datetime, payload: Dict[str, Any]) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO readings (
                    timestamp,
                    wind_speed,
                    wind_dir,
                    wind_gust,
                    rain_rate,
                    rain_total,
                    temperature,
                    humidity,
                    uv,
                    solar_radiation,
                    pressure,
                    indoor_temperature,
                    indoor_humidity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp.isoformat(),
                    payload.get("wind_speed"),
                    payload.get("wind_dir"),
                    payload.get("wind_gust"),
                    payload.get("rain_rate"),
                    payload.get("rain_total"),
                    payload.get("temperature"),
                    payload.get("humidity"),
                    payload.get("uv"),
                    payload.get("solar_radiation"),
                    payload.get("pressure"),
                    payload.get("indoor_temperature"),
                    payload.get("indoor_humidity"),
                ),
            )
            connection.commit()

    def get_latest(self) -> Optional[Dict[str, Optional[float]]]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, row))

    def export_readings(self, max_days: int, format: str = "csv") -> str:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_days)
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM readings WHERE timestamp >= ? ORDER BY timestamp DESC",
                (cutoff.isoformat(),),
            )
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]

        if format == "json":
            import json

            return json.dumps([dict(zip(columns, row)) for row in rows], default=str)

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
        return output.getvalue().rstrip("\n")

    def prune_readings(self, retention_days: int) -> None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days)
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM readings WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            connection.commit()
