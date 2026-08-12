import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional


ADDITIONAL_READING_COLUMNS = {
    "dew_point": "REAL",
    "wind_chill": "REAL",
    "heat_index": "REAL",
    "absolute_pressure": "REAL",
    "daily_max_wind": "REAL",
    "rain_increment": "REAL",
    "rain_event": "REAL",
    "rain_week": "REAL",
    "rain_month": "REAL",
    "rain_year": "REAL",
    "rain_lifetime": "REAL",
    "light_intensity": "REAL",
    "indoor_pressure": "REAL",
    "indoor_absolute_pressure": "REAL",
}


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
            existing_columns = {
                str(row[1]) for row in cursor.execute("PRAGMA table_info(readings)")
            }
            for name, column_type in ADDITIONAL_READING_COLUMNS.items():
                if name not in existing_columns:
                    cursor.execute(
                        f"ALTER TABLE readings ADD COLUMN {name} {column_type}"
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
                    indoor_humidity,
                    dew_point,
                    wind_chill,
                    heat_index,
                    absolute_pressure,
                    daily_max_wind,
                    rain_increment,
                    rain_event,
                    rain_week,
                    rain_month,
                    rain_year,
                    rain_lifetime,
                    light_intensity,
                    indoor_pressure,
                    indoor_absolute_pressure
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    payload.get("dew_point"),
                    payload.get("wind_chill"),
                    payload.get("heat_index"),
                    payload.get("absolute_pressure"),
                    payload.get("daily_max_wind"),
                    payload.get("rain_increment"),
                    payload.get("rain_event"),
                    payload.get("rain_week"),
                    payload.get("rain_month"),
                    payload.get("rain_year"),
                    payload.get("rain_lifetime"),
                    payload.get("light_intensity"),
                    payload.get("indoor_pressure"),
                    payload.get("indoor_absolute_pressure"),
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

    def get_readings_since(self, cutoff: datetime) -> list[Dict[str, Any]]:
        """Return chronologically ordered readings at or after a UTC cutoff."""
        if cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM readings WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff.isoformat(),),
            )
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

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
