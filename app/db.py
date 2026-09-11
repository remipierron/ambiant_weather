"""Accès SQLite partagé entre les 4 services (capteur, météo, entraînement, API).

La base est un unique fichier SQLite monté en volume Docker partagé. Le mode
WAL est activé pour permettre les accès concurrents en lecture/écriture
depuis plusieurs conteneurs sans erreurs de verrouillage.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS room_measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL UNIQUE,      -- horodatage UTC ISO8601, arrondi à la seconde
    temperature REAL,
    humidity    REAL,
    pressure    REAL
);

CREATE TABLE IF NOT EXISTS weather_observed (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL UNIQUE,      -- heure pleine UTC ISO8601
    temperature REAL,
    humidity    REAL,
    pressure    REAL,
    cloud_cover REAL,
    wind_speed  REAL,
    precipitation REAL,
    source      TEXT DEFAULT 'open-meteo'
);

CREATE TABLE IF NOT EXISTS weather_forecast (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issued_at   TEXT NOT NULL,             -- horodatage UTC de récupération de la prévision
    target_ts   TEXT NOT NULL,             -- heure pleine UTC visée par la prévision
    temperature REAL,
    humidity    REAL,
    pressure    REAL,
    cloud_cover REAL,
    wind_speed  REAL,
    precipitation REAL,
    UNIQUE(issued_at, target_ts)
);

CREATE TABLE IF NOT EXISTS predictions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at           TEXT NOT NULL,  -- horodatage UTC de génération
    target_ts              TEXT NOT NULL,  -- heure pleine UTC prédite
    predicted_temperature  REAL,
    predicted_humidity     REAL,
    predicted_pressure     REAL,
    model_version          TEXT,
    UNIQUE(generated_at, target_ts)
);

CREATE INDEX IF NOT EXISTS idx_room_ts ON room_measurements(ts);
CREATE INDEX IF NOT EXISTS idx_weather_observed_ts ON weather_observed(ts);
CREATE INDEX IF NOT EXISTS idx_weather_forecast_target ON weather_forecast(target_ts);
CREATE INDEX IF NOT EXISTS idx_predictions_generated ON predictions(generated_at);
"""


def init_db(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA)


@contextlib.contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Mesures de la chambre (capteur BME280)
# --------------------------------------------------------------------------

def insert_room_measurement(
    ts: str, temperature: float, humidity: float, pressure: float, db_path: str | None = None
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO room_measurements (ts, temperature, humidity, pressure) "
            "VALUES (?, ?, ?, ?)",
            (ts, temperature, humidity, pressure),
        )


def get_room_measurements(
    start: str | None = None, end: str | None = None, db_path: str | None = None
) -> list[sqlite3.Row]:
    query = "SELECT ts, temperature, humidity, pressure FROM room_measurements WHERE 1=1"
    params: list[str] = []
    if start:
        query += " AND ts >= ?"
        params.append(start)
    if end:
        query += " AND ts <= ?"
        params.append(end)
    query += " ORDER BY ts ASC"
    with get_connection(db_path) as conn:
        return conn.execute(query, params).fetchall()


def get_latest_room_measurement(db_path: str | None = None) -> sqlite3.Row | None:
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT ts, temperature, humidity, pressure FROM room_measurements "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()


# --------------------------------------------------------------------------
# Météo observée (historique + reconstitution récente)
# --------------------------------------------------------------------------

def upsert_weather_observed(records: Iterable[dict], db_path: str | None = None) -> int:
    records = list(records)
    if not records:
        return 0
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO weather_observed
                (ts, temperature, humidity, pressure, cloud_cover, wind_speed, precipitation, source)
            VALUES (:ts, :temperature, :humidity, :pressure, :cloud_cover, :wind_speed, :precipitation, :source)
            ON CONFLICT(ts) DO UPDATE SET
                temperature=excluded.temperature,
                humidity=excluded.humidity,
                pressure=excluded.pressure,
                cloud_cover=excluded.cloud_cover,
                wind_speed=excluded.wind_speed,
                precipitation=excluded.precipitation,
                source=excluded.source
            """,
            records,
        )
    return len(records)


def get_weather_observed(
    start: str | None = None, end: str | None = None, db_path: str | None = None
) -> list[sqlite3.Row]:
    query = "SELECT * FROM weather_observed WHERE 1=1"
    params: list[str] = []
    if start:
        query += " AND ts >= ?"
        params.append(start)
    if end:
        query += " AND ts <= ?"
        params.append(end)
    query += " ORDER BY ts ASC"
    with get_connection(db_path) as conn:
        return conn.execute(query, params).fetchall()


def get_latest_weather_observed_ts(db_path: str | None = None) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT MAX(ts) AS max_ts FROM weather_observed").fetchone()
        return row["max_ts"] if row else None


# --------------------------------------------------------------------------
# Prévisions météo (telles qu'émises)
# --------------------------------------------------------------------------

def insert_weather_forecast(issued_at: str, records: Iterable[dict], db_path: str | None = None) -> int:
    records = list(records)
    if not records:
        return 0
    for r in records:
        r["issued_at"] = issued_at
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO weather_forecast
                (issued_at, target_ts, temperature, humidity, pressure, cloud_cover, wind_speed, precipitation)
            VALUES (:issued_at, :ts, :temperature, :humidity, :pressure, :cloud_cover, :wind_speed, :precipitation)
            """,
            records,
        )
    return len(records)


def get_latest_forecast_batch(db_path: str | None = None) -> list[sqlite3.Row]:
    """Renvoie la prévision la plus récemment émise (tous les horizons confondus)."""
    with get_connection(db_path) as conn:
        latest = conn.execute("SELECT MAX(issued_at) AS issued_at FROM weather_forecast").fetchone()
        if not latest or not latest["issued_at"]:
            return []
        return conn.execute(
            "SELECT * FROM weather_forecast WHERE issued_at = ? ORDER BY target_ts ASC",
            (latest["issued_at"],),
        ).fetchall()


# --------------------------------------------------------------------------
# Prédictions générées par nos modèles
# --------------------------------------------------------------------------

def insert_predictions(generated_at: str, records: Iterable[dict], model_version: str, db_path: str | None = None) -> int:
    records = list(records)
    if not records:
        return 0
    for r in records:
        r["generated_at"] = generated_at
        r["model_version"] = model_version
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO predictions
                (generated_at, target_ts, predicted_temperature, predicted_humidity, predicted_pressure, model_version)
            VALUES (:generated_at, :target_ts, :predicted_temperature, :predicted_humidity, :predicted_pressure, :model_version)
            """,
            records,
        )
    return len(records)


def get_latest_predictions(db_path: str | None = None) -> list[sqlite3.Row]:
    with get_connection(db_path) as conn:
        latest = conn.execute("SELECT MAX(generated_at) AS generated_at FROM predictions").fetchone()
        if not latest or not latest["generated_at"]:
            return []
        return conn.execute(
            "SELECT * FROM predictions WHERE generated_at = ? ORDER BY target_ts ASC",
            (latest["generated_at"],),
        ).fetchall()


def rows_to_dicts(rows: Sequence[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
