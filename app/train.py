"""Entraînement des modèles de prédiction de la chambre.

Deux familles de modèles sont entraînées et comparées à chaque cycle
(voir README, section "Choix technique") :
- `baseline` : régression linéaire multiple (un modèle par cible), sert de
  référence honnête.
- `gbm` : gradient boosting (LightGBM, un modèle par cible), modèle retenu
  pour la mise en production tant qu'il fait mieux que la baseline.

Le découpage train/test est chronologique (pas de mélange aléatoire) pour
évaluer une vraie capacité de généralisation temporelle. Les modèles et les
métriques sont sauvegardés dans `MODELS_DIR` ; `app.predict` charge toujours
la dernière version entraînée.

Utilisation :
    python -m app.train
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error

from app.config import settings
from app.db import get_room_measurements, get_weather_observed, init_db
from app.features import FEATURE_COLUMNS, TARGET_COLS, build_training_frame

logging.basicConfig(level=logging.INFO, format="%(asctime)s [train] %(message)s")
logger = logging.getLogger(__name__)


def _split_train_test(df: pd.DataFrame, test_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_test = max(1, int(len(df) * test_fraction))
    return df.iloc[:-n_test], df.iloc[-n_test:]


def _evaluate(model, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    preds = model.predict(X_test)
    return {
        "mae": float(mean_absolute_error(y_test, preds)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, preds))),
        "n_test": int(len(y_test)),
    }


def train_all(db_path: str | None = None, models_dir: str | None = None) -> dict | None:
    """Entraîne baseline + gradient boosting pour les 3 cibles. Renvoie les métadonnées, ou None si pas assez de données."""
    init_db(db_path)
    room_rows = get_room_measurements(db_path=db_path)
    weather_rows = get_weather_observed(db_path=db_path)

    df, feature_cols = build_training_frame(room_rows, weather_rows)

    if len(df) < settings.min_training_rows:
        logger.warning(
            "Pas assez de données pour entraîner (%s lignes exploitables, minimum %s requis).",
            len(df),
            settings.min_training_rows,
        )
        return None

    train_df, test_df = _split_train_test(df, settings.test_fraction)
    X_train, X_test = train_df[feature_cols], test_df[feature_cols]

    models_dir = Path(models_dir or settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    metrics: dict[str, dict] = {}

    for target_col in TARGET_COLS:
        var = target_col.replace("target_", "")
        y_train, y_test = train_df[target_col], test_df[target_col]

        baseline = LinearRegression()
        baseline.fit(X_train, y_train)
        baseline_metrics = _evaluate(baseline, X_test, y_test)

        gbm = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=15,
            min_child_samples=5,
            verbosity=-1,
        )
        gbm.fit(X_train, y_train)
        gbm_metrics = _evaluate(gbm, X_test, y_test)

        joblib.dump(baseline, models_dir / f"baseline_{var}.joblib")
        joblib.dump(gbm, models_dir / f"gbm_{var}.joblib")

        metrics[var] = {"baseline": baseline_metrics, "gbm": gbm_metrics}

        logger.info(
            "%-11s baseline MAE=%.3f RMSE=%.3f | gbm MAE=%.3f RMSE=%.3f (n_test=%s)",
            var,
            baseline_metrics["mae"],
            baseline_metrics["rmse"],
            gbm_metrics["mae"],
            gbm_metrics["rmse"],
            gbm_metrics["n_test"],
        )

    metadata = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rows_total": int(len(df)),
        "n_rows_train": int(len(train_df)),
        "n_rows_test": int(len(test_df)),
        "feature_columns": feature_cols,
        "metrics": metrics,
    }

    (models_dir / "feature_columns.json").write_text(json.dumps(feature_cols, indent=2))
    (models_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    logger.info("Entraînement terminé (version %s, %s lignes).", version, len(df))
    return metadata


if __name__ == "__main__":
    train_all()
