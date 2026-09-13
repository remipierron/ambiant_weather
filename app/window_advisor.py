"""Conseil "fenêtres" : à quelle heure les fermer le matin pour garder la fraîcheur.

Contrairement au système de prédiction (`app.predict`), qui a besoin de
plusieurs jours de données croisées chambre + météo pour être entraîné, ce
conseil ne repose que sur la dernière mesure de la chambre et les prévisions
météo extérieures déjà disponibles (`weather_forecast`) : il est donc
utilisable dès le premier jour, sans attendre `MIN_TRAINING_ROWS`.

Principe : le matin, on ouvre les fenêtres pour faire entrer l'air frais tant
que la température extérieure est plus basse que la température intérieure.
Dès que la température extérieure dépasse la température intérieure
(projetée), continuer à aérer réchaufferait la pièce au lieu de la
rafraîchir : c'est l'heure optimale pour fermer. On cherche donc le premier
croisement entre :
- la courbe de température extérieure prévue (heure par heure),
- une projection simple de la température intérieure, obtenue en prolongeant
  sa pente récente (régression linéaire sur les dernières heures).

Utilisation :
    python -m app.window_advisor
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.config import settings
from app.db import (
    get_latest_forecast_batch,
    get_latest_room_measurement,
    get_room_measurements,
    init_db,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [window_advisor] %(message)s")
logger = logging.getLogger(__name__)


def _indoor_trend_per_hour(now: datetime, db_path: str | None = None) -> float:
    """Pente récente (°C/h) de la température intérieure.

    Renvoie 0.0 si moins de deux mesures sur la fenêtre de calcul (repli sur
    une température intérieure supposée stable, faute de mieux).
    """
    start = (now - timedelta(hours=settings.window_advice_trend_lookback_hours)).isoformat(timespec="seconds")
    rows = get_room_measurements(start=start, db_path=db_path)
    if len(rows) < 2:
        return 0.0

    df = pd.DataFrame([dict(r) for r in rows])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.dropna(subset=["temperature"]).sort_values("ts")
    if len(df) < 2:
        return 0.0

    elapsed_hours = (df["ts"] - df["ts"].iloc[0]).dt.total_seconds() / 3600
    if elapsed_hours.iloc[-1] == 0:
        return 0.0

    slope, _ = np.polyfit(elapsed_hours, df["temperature"], 1)
    return float(slope)


def compute_window_advice(db_path: str | None = None) -> dict:
    """Calcule le conseil de fermeture des fenêtres à partir des données disponibles."""
    init_db(db_path)
    now = datetime.now(timezone.utc)

    latest_room = get_latest_room_measurement(db_path=db_path)
    if latest_room is None or latest_room["temperature"] is None:
        return {"available": False, "reason": "Aucune mesure de la chambre disponible."}

    forecast_rows = get_latest_forecast_batch(db_path=db_path)
    if not forecast_rows:
        return {"available": False, "reason": "Aucune prévision météo disponible."}

    forecast_df = pd.DataFrame([dict(r) for r in forecast_rows])
    forecast_df["ts"] = pd.to_datetime(forecast_df["target_ts"], utc=True)
    forecast_df = forecast_df.dropna(subset=["temperature"]).sort_values("ts")
    forecast_df = forecast_df[forecast_df["ts"] >= pd.Timestamp(now).floor("h")]
    forecast_df = forecast_df.head(settings.window_advice_lookahead_hours)

    if forecast_df.empty:
        return {"available": False, "reason": "Prévisions météo insuffisantes pour l'horizon demandé."}

    indoor_temp0 = float(latest_room["temperature"])
    # Une pente montante (chambre qui se réchauffe, fenêtres pas encore
    # ouvertes) n'a pas de sens à prolonger ici : on ne projette que le
    # refroidissement, jamais un réchauffement dû à l'aération elle-même.
    indoor_slope = min(_indoor_trend_per_hour(now, db_path=db_path), 0.0)

    now_ts = pd.Timestamp(now)
    hourly: list[dict] = []
    crossing_ts: pd.Timestamp | None = None

    for _, row in forecast_df.iterrows():
        elapsed_h = max((row["ts"] - now_ts).total_seconds() / 3600, 0.0)
        indoor_projected = indoor_temp0 + indoor_slope * elapsed_h
        outdoor = float(row["temperature"])
        hourly.append(
            {
                "ts": row["ts"].isoformat(),
                "outdoor_temperature": outdoor,
                "indoor_projected_temperature": round(indoor_projected, 2),
            }
        )
        if crossing_ts is None and outdoor >= indoor_projected:
            crossing_ts = row["ts"]

    advice: dict
    if crossing_ts is None:
        advice = {
            "should_close": False,
            "recommended_close_time": None,
            "message": (
                "La température extérieure prévue reste sous la température intérieure "
                f"sur les {settings.window_advice_lookahead_hours} prochaines heures : "
                "vous pouvez garder les fenêtres ouvertes."
            ),
        }
    elif crossing_ts <= now_ts:
        advice = {
            "should_close": True,
            "recommended_close_time": crossing_ts.isoformat(),
            "message": "La température extérieure a déjà rejoint la température intérieure : fermez les fenêtres maintenant.",
        }
    else:
        local_time = crossing_ts.tz_convert(settings.timezone).strftime("%Hh%M")
        advice = {
            "should_close": True,
            "recommended_close_time": crossing_ts.isoformat(),
            "message": f"Fermez les fenêtres vers {local_time} (heure locale) pour garder l'air frais.",
        }

    advice.update(
        {
            "available": True,
            "as_of": now.isoformat(timespec="seconds"),
            "current_indoor_temperature": indoor_temp0,
            "indoor_trend_per_hour": round(indoor_slope, 3),
            "hourly": hourly,
        }
    )
    return advice


if __name__ == "__main__":
    result = compute_window_advice()
    logger.info("%s", result.get("message", result.get("reason")))
