"""Génération des prédictions de la chambre sur les prochaines heures.

Charge les derniers modèles entraînés (`app.train`) et applique une
prédiction "récursive" heure par heure jusqu'à `FORECAST_HORIZON_HOURS` :
la sortie prédite à t+1 devient l'entrée "courante" pour prédire t+2, etc.
Les prévisions météo extérieures (déjà connues à l'avance) proviennent de
`weather_forecast` ; au-delà de l'horizon couvert par l'API, la dernière
valeur connue est simplement reconduite (persistance).

Utilisation :
    python -m app.predict
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from app.config import settings
from app.db import (
    get_latest_forecast_batch,
    get_room_measurements,
    get_weather_observed,
    init_db,
    insert_predictions,
)
from app.features import (
    FEATURE_COLUMNS,
    LAG_HOURS,
    MAX_LAG_HOURS,
    OUT_VARS,
    ROOM_VARS,
    build_inference_row,
    resample_room_hourly,
    resample_weather_hourly,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [predict] %(message)s")
logger = logging.getLogger(__name__)


class ModelsNotReady(RuntimeError):
    """Levée quand aucun modèle entraîné n'est disponible."""


def load_models(models_dir: str | None = None) -> tuple[dict, list[str], dict]:
    directory = Path(models_dir or settings.models_dir)
    metadata_path = directory / "metadata.json"
    if not metadata_path.exists():
        raise ModelsNotReady(f"Aucun modèle entraîné trouvé dans {directory} (lancez d'abord app.train).")

    metadata = json.loads(metadata_path.read_text())
    feature_columns = metadata.get("feature_columns", FEATURE_COLUMNS)

    models = {var: joblib.load(directory / f"gbm_{var}.joblib") for var in ROOM_VARS}
    return models, feature_columns, metadata


def _build_weather_lookup(weather_rows, forecast_rows, horizon_end: pd.Timestamp) -> pd.DataFrame:
    observed = resample_weather_hourly(weather_rows)

    forecast_records = [dict(r) for r in forecast_rows]
    if forecast_records:
        forecast_df = pd.DataFrame(forecast_records)
        forecast_df["ts"] = pd.to_datetime(forecast_df["target_ts"], utc=True)
        forecast_df = forecast_df.set_index("ts")[list(OUT_VARS)].astype(float)
        forecast_df = forecast_df[~forecast_df.index.duplicated(keep="last")].sort_index()
    else:
        forecast_df = pd.DataFrame(columns=list(OUT_VARS))

    if observed.empty and forecast_df.empty:
        return pd.DataFrame(columns=list(OUT_VARS))

    # L'observé fait foi ; la prévision comble les heures manquantes (le futur).
    combined = observed.combine_first(forecast_df) if not observed.empty else forecast_df

    full_index = pd.date_range(combined.index.min(), horizon_end, freq="1h", tz="UTC")
    combined = combined.reindex(combined.index.union(full_index)).sort_index()
    combined = combined.ffill().bfill()
    return combined


def generate_predictions(db_path: str | None = None, models_dir: str | None = None) -> list[dict]:
    init_db(db_path)
    models, feature_columns, metadata = load_models(models_dir)

    room_rows = get_room_measurements(db_path=db_path)
    weather_rows = get_weather_observed(db_path=db_path)
    forecast_rows = get_latest_forecast_batch(db_path=db_path)

    room_hourly = resample_room_hourly(room_rows)
    if room_hourly.empty:
        raise ModelsNotReady("Aucune mesure de chambre en base, impossible de prédire.")

    t0 = room_hourly.index.max()
    horizon = settings.forecast_horizon_hours
    horizon_end = t0 + pd.Timedelta(hours=horizon)

    weather_lookup = _build_weather_lookup(weather_rows, forecast_rows, horizon_end)
    if weather_lookup.empty:
        raise ModelsNotReady("Aucune donnée météo en base, impossible de prédire.")

    # Historique récent nécessaire pour les lags (jusqu'à MAX_LAG_HOURS en arrière).
    history: dict[pd.Timestamp, dict] = {
        ts: {var: row[f"{var}"] for var in ROOM_VARS}
        for ts, row in room_hourly.tail(MAX_LAG_HOURS + 1).iterrows()
    }

    current_t = t0
    current_state = history[t0]

    predictions: list[dict] = []
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for _ in range(horizon):
        target_ts = current_t + pd.Timedelta(hours=1)

        lag_values = {
            lag: history.get(current_t - pd.Timedelta(hours=lag), current_state) for lag in LAG_HOURS
        }
        out_now = weather_lookup.loc[current_t].to_dict() if current_t in weather_lookup.index else {}
        out_next = weather_lookup.loc[target_ts].to_dict() if target_ts in weather_lookup.index else {}

        row = build_inference_row(current_state, lag_values, out_now, out_next, target_ts)
        X = pd.DataFrame([row])[feature_columns]

        predicted = {var: float(models[var].predict(X)[0]) for var in ROOM_VARS}

        history[target_ts] = predicted
        predictions.append(
            {
                "target_ts": target_ts.isoformat(),
                "predicted_temperature": predicted["temperature"],
                "predicted_humidity": predicted["humidity"],
                "predicted_pressure": predicted["pressure"],
            }
        )

        current_state = predicted
        current_t = target_ts

    n = insert_predictions(generated_at, predictions, model_version=metadata.get("version", "unknown"), db_path=db_path)
    logger.info("Prédictions générées : %s heures (à partir de %s, modèle %s).", n, t0, metadata.get("version"))
    return predictions


if __name__ == "__main__":
    generate_predictions()
