"""Tests pour app.window_advisor : conseil d'heure de fermeture des fenêtres.

Contrairement au pipeline d'entraînement/prédiction, ce conseil ne doit
nécessiter que la dernière mesure de la chambre + une prévision météo — pas
d'historique de plusieurs jours.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import (
    init_db,
    insert_room_measurement,
    insert_weather_forecast,
)
from app.window_advisor import compute_window_advice


def test_unavailable_without_room_measurement(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)

    advice = compute_window_advice(db_path=db_path)
    assert advice["available"] is False


def test_unavailable_without_forecast(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)
    now = datetime.now(timezone.utc)
    insert_room_measurement(now.isoformat(timespec="seconds"), 21.0, 45.0, 1015.0, db_path=db_path)

    advice = compute_window_advice(db_path=db_path)
    assert advice["available"] is False


def test_recommends_keeping_windows_open_when_outdoor_stays_cool(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)
    now = datetime.now(timezone.utc)
    insert_room_measurement(now.isoformat(timespec="seconds"), 22.0, 45.0, 1015.0, db_path=db_path)

    # Prévision toujours nettement plus fraîche que l'intérieur.
    forecast = [
        {
            "ts": (now + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0).isoformat(),
            "temperature": 15.0,
            "humidity": 60.0,
            "pressure": 1012.0,
            "cloud_cover": 20.0,
            "wind_speed": 3.0,
            "precipitation": 0.0,
        }
        for h in range(1, 16)
    ]
    insert_weather_forecast(now.isoformat(timespec="seconds"), forecast, db_path=db_path)

    advice = compute_window_advice(db_path=db_path)
    assert advice["available"] is True
    assert advice["should_close"] is False
    assert advice["recommended_close_time"] is None


def test_recommends_closing_when_outdoor_crosses_above_indoor(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    init_db(db_path)
    now = datetime.now(timezone.utc)
    insert_room_measurement(now.isoformat(timespec="seconds"), 20.0, 45.0, 1015.0, db_path=db_path)

    # Prévision qui monte progressivement au-dessus de la température intérieure.
    forecast = [
        {
            "ts": (now + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0).isoformat(),
            "temperature": 14.0 + h,  # dépasse 20°C à partir de h=6
            "humidity": 60.0,
            "pressure": 1012.0,
            "cloud_cover": 20.0,
            "wind_speed": 3.0,
            "precipitation": 0.0,
        }
        for h in range(1, 16)
    ]
    insert_weather_forecast(now.isoformat(timespec="seconds"), forecast, db_path=db_path)

    advice = compute_window_advice(db_path=db_path)
    assert advice["available"] is True
    assert advice["should_close"] is True
    assert advice["recommended_close_time"] is not None
