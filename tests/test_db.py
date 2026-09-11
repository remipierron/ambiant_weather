"""Tests pour app.db (SQLite), isolés dans un fichier temporaire."""

from __future__ import annotations

from app.db import (
    get_latest_room_measurement,
    get_room_measurements,
    get_weather_observed,
    init_db,
    insert_room_measurement,
    upsert_weather_observed,
)


def test_room_measurement_roundtrip(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)

    insert_room_measurement("2026-01-01T00:00:00+00:00", 20.0, 45.0, 1015.0, db_path=db_path)
    insert_room_measurement("2026-01-01T01:00:00+00:00", 20.5, 46.0, 1015.2, db_path=db_path)
    # doublon ignoré (contrainte UNIQUE sur ts)
    insert_room_measurement("2026-01-01T01:00:00+00:00", 999.0, 999.0, 999.0, db_path=db_path)

    rows = get_room_measurements(db_path=db_path)
    assert len(rows) == 2
    assert rows[1]["temperature"] == 20.5

    latest = get_latest_room_measurement(db_path=db_path)
    assert latest["ts"] == "2026-01-01T01:00:00+00:00"


def test_weather_observed_upsert_updates_existing(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)

    record = {
        "ts": "2026-01-01T00:00:00+00:00",
        "temperature": 10.0,
        "humidity": 60.0,
        "pressure": 1012.0,
        "cloud_cover": 50.0,
        "wind_speed": 3.0,
        "precipitation": 0.0,
        "source": "open-meteo",
    }
    upsert_weather_observed([record], db_path=db_path)

    updated = dict(record)
    updated["temperature"] = 11.5
    upsert_weather_observed([updated], db_path=db_path)

    rows = get_weather_observed(db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["temperature"] == 11.5
