"""Test d'intégration bout-en-bout : DB synthétique -> entraînement -> prédiction.

Ne fait aucun appel réseau (pas d'Open-Meteo) : les données météo sont
générées synthétiquement, comme le ferait `app.weather_sync` une fois
alimenté par l'API réelle.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.db import (
    init_db,
    insert_room_measurement,
    insert_weather_forecast,
    upsert_weather_observed,
)
from app.predict import generate_predictions
from app.train import train_all


def _seed_synthetic_data(db_path: str, days: int = 30):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    hours = days * 24

    for i in range(hours):
        ts = (start + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        outdoor_temp = 12 + 8 * math.sin(2 * math.pi * i / 24) + 3 * math.sin(2 * math.pi * i / (24 * 7))
        room_temp = 19 + 0.3 * outdoor_temp + 0.5 * math.sin(2 * math.pi * i / 24)

        upsert_weather_observed(
            [
                {
                    "ts": ts.isoformat(),
                    "temperature": outdoor_temp,
                    "humidity": 55 + 10 * math.sin(2 * math.pi * i / 24),
                    "pressure": 1013 + math.sin(i / 50),
                    "cloud_cover": 40.0,
                    "wind_speed": 5.0,
                    "precipitation": 0.0,
                    "source": "test",
                }
            ],
            db_path=db_path,
        )
        insert_room_measurement(
            ts.isoformat(),
            room_temp,
            45 + 5 * math.sin(2 * math.pi * i / 24),
            1015 + math.sin(i / 60),
            db_path=db_path,
        )

    # Prévision météo pour les prochaines 48h, émise "maintenant".
    now = datetime.now(timezone.utc)
    forecast_records = []
    for h in range(1, 49):
        ts = (now + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0)
        outdoor_temp = 12 + 8 * math.sin(2 * math.pi * (hours + h) / 24)
        forecast_records.append(
            {
                "ts": ts.isoformat(),
                "temperature": outdoor_temp,
                "humidity": 55.0,
                "pressure": 1013.0,
                "cloud_cover": 40.0,
                "wind_speed": 5.0,
                "precipitation": 0.0,
            }
        )
    insert_weather_forecast(now.isoformat(timespec="seconds"), forecast_records, db_path=db_path)


def test_train_and_predict_end_to_end(tmp_path):
    db_path = str(tmp_path / "meteo.db")
    models_dir = str(tmp_path / "models")
    init_db(db_path)

    _seed_synthetic_data(db_path, days=30)

    metadata = train_all(db_path=db_path, models_dir=models_dir)
    assert metadata is not None
    assert metadata["n_rows_total"] > 0
    for var in ("temperature", "humidity", "pressure"):
        assert var in metadata["metrics"]
        assert metadata["metrics"][var]["gbm"]["mae"] >= 0

    predictions = generate_predictions(db_path=db_path, models_dir=models_dir)
    assert len(predictions) == 48  # FORECAST_HORIZON_HOURS par défaut

    for p in predictions:
        assert -50 < p["predicted_temperature"] < 60
        assert 0 <= p["predicted_humidity"] <= 100
        assert 900 < p["predicted_pressure"] < 1100

    # La prédiction à 1h doit être raisonnablement proche de la dernière
    # mesure réelle (pas de divergence explosive dès le premier pas).
    from app.db import get_latest_room_measurement

    latest = get_latest_room_measurement(db_path=db_path)
    assert abs(predictions[0]["predicted_temperature"] - latest["temperature"]) < 15
