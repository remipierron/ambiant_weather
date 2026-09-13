"""Tests unitaires pour le feature engineering (app.features), sans dépendance
à la base de données ni au réseau."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.features import FEATURE_COLUMNS, TARGET_COLS, build_training_frame


def _make_rows(n_hours: int, start: datetime, room_fn, weather_fn):
    room_rows = []
    weather_rows = []
    for i in range(n_hours):
        ts = (start + timedelta(hours=i)).isoformat()
        t, h, p = room_fn(i)
        room_rows.append({"ts": ts, "temperature": t, "humidity": h, "pressure": p})
        t, h, p, c, w, pr = weather_fn(i)
        weather_rows.append(
            {
                "ts": ts,
                "temperature": t,
                "humidity": h,
                "pressure": p,
                "cloud_cover": c,
                "wind_speed": w,
                "precipitation": pr,
            }
        )
    return room_rows, weather_rows


def test_build_training_frame_shapes_and_no_nan():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = 200

    room_fn = lambda i: (20 + 0.01 * i, 45 + math.sin(i / 5), 1015)
    weather_fn = lambda i: (10 + 0.02 * i, 60, 1012, 50, 3, 0)

    room_rows, weather_rows = _make_rows(n, start, room_fn, weather_fn)

    df, feature_cols = build_training_frame(room_rows, weather_rows)

    assert feature_cols == FEATURE_COLUMNS
    assert not df.empty
    # Les lags se replient sur la valeur courante quand l'historique manque
    # (voir app.features) : seule l'heure la plus récente est perdue, à
    # cause du décalage -1h utilisé pour construire la cible/météo "next".
    assert len(df) == n - 1
    for col in feature_cols + TARGET_COLS:
        assert col in df.columns
        assert not df[col].isna().any()


def test_lag_falls_back_to_current_value_when_history_missing():
    """Avec peu d'historique (< 24h), room_*_lag24 doit valoir room_* (repli),
    pas être absent — c'est ce qui permet d'entraîner dès le premier jour."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = 5
    room_fn = lambda i: (20.0 + i, 45.0, 1015.0)
    weather_fn = lambda i: (10.0, 60.0, 1012.0, 50.0, 3.0, 0.0)
    room_rows, weather_rows = _make_rows(n, start, room_fn, weather_fn)

    df, _ = build_training_frame(room_rows, weather_rows)

    assert not df.empty
    assert (df["room_temperature_lag24"] == df["room_temperature"]).all()


def test_build_training_frame_empty_when_no_overlap():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    room_rows, _ = _make_rows(50, start, lambda i: (20, 45, 1015), lambda i: (10, 60, 1012, 50, 3, 0))
    # Météo décalée de 10 jours : aucune heure commune avec les mesures de la chambre.
    _, weather_rows = _make_rows(50, start + timedelta(days=10), lambda i: (20, 45, 1015), lambda i: (10, 60, 1012, 50, 3, 0))

    df, _ = build_training_frame(room_rows, weather_rows)
    assert df.empty


def test_target_is_next_hour_room_value():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = 100
    room_fn = lambda i: (float(i), 45.0, 1015.0)
    weather_fn = lambda i: (10.0, 60.0, 1012.0, 50.0, 3.0, 0.0)
    room_rows, weather_rows = _make_rows(n, start, room_fn, weather_fn)

    df, _ = build_training_frame(room_rows, weather_rows)

    # room_temperature vaut i ; la cible à l'index i doit valoir i+1.
    for ts, row in df.iterrows():
        assert row["target_temperature"] == pytest.approx(row["room_temperature"] + 1)
