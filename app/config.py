"""Configuration centralisée, lue depuis les variables d'environnement.

Toutes les variables ont une valeur par défaut raisonnable pour pouvoir
lancer le projet en local sans rien configurer (mode "mock" pour le capteur,
coordonnées de la chambre à Niort par défaut, etc.). En production
(Raspberry Pi via Docker Compose), on surcharge via le fichier `.env`
(voir `.env.example`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    # Optionnel : permet de charger un fichier .env en dev local (hors Docker,
    # où les variables sont déjà injectées par docker-compose).
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dépendance optionnelle
    pass


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Stockage ---
    db_path: str = os.getenv("DB_PATH", "./data/meteo.db")
    models_dir: str = os.getenv("MODELS_DIR", "./data/models")

    # --- Localisation (par défaut : 22 rue du Grand Port, 79000 Niort) ---
    latitude: float = float(os.getenv("LATITUDE", "46.3197"))
    longitude: float = float(os.getenv("LONGITUDE", "-0.5306"))
    timezone: str = os.getenv("TIMEZONE", "Europe/Paris")

    # --- Capteur BME280 ---
    sensor_i2c_port: int = int(os.getenv("SENSOR_I2C_PORT", "1"))
    sensor_i2c_address: int = int(os.getenv("SENSOR_I2C_ADDRESS", "0x77"), 0)
    sensor_interval_seconds: int = int(os.getenv("SENSOR_INTERVAL_SECONDS", "60"))
    # Mode simulation (aucun capteur/hardware requis) : pratique en dev sur
    # un poste qui n'est pas le Raspberry Pi, ou pour les tests.
    sensor_mock: bool = _bool("SENSOR_MOCK", "false")

    # --- Synchronisation météo (Open-Meteo) ---
    weather_sync_interval_minutes: int = int(os.getenv("WEATHER_SYNC_INTERVAL_MINUTES", "60"))
    # Date de départ du backfill historique si la base est vide.
    weather_history_start_date: str = os.getenv("WEATHER_HISTORY_START_DATE", "2024-01-01")
    forecast_days: int = int(os.getenv("FORECAST_DAYS", "16"))
    past_days: int = int(os.getenv("WEATHER_PAST_DAYS", "5"))

    # --- Entraînement / prédiction ---
    train_interval_hours: int = int(os.getenv("TRAIN_INTERVAL_HOURS", "24"))
    # Abaissé de 72 à 24 : grâce au repli des lags sur la valeur courante
    # (voir app.features), un premier modèle exploitable n'a plus besoin
    # d'attendre plusieurs jours de mesures.
    min_training_rows: int = int(os.getenv("MIN_TRAINING_ROWS", "24"))
    test_fraction: float = float(os.getenv("TEST_FRACTION", "0.2"))
    forecast_horizon_hours: int = int(os.getenv("FORECAST_HORIZON_HOURS", "48"))
    predict_interval_minutes: int = int(os.getenv("PREDICT_INTERVAL_MINUTES", "30"))

    # --- Conseil fenêtres (voir app.window_advisor) ---
    # Horizon (en heures, à partir de maintenant) sur lequel on cherche le
    # croisement température extérieure / intérieure pour conseiller l'heure
    # de fermeture des fenêtres.
    window_advice_lookahead_hours: int = int(os.getenv("WINDOW_ADVICE_LOOKAHEAD_HOURS", "15"))
    # Fenêtre (en heures) sur laquelle on estime la pente récente de la
    # température intérieure (pour projeter son évolution pendant l'aération).
    window_advice_trend_lookback_hours: int = int(os.getenv("WINDOW_ADVICE_TREND_LOOKBACK_HOURS", "3"))

    # --- API ---
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    hourly_variables: tuple[str, ...] = field(
        default_factory=lambda: (
            "temperature_2m",
            "relative_humidity_2m",
            "surface_pressure",
            "cloud_cover",
            "wind_speed_10m",
            "precipitation",
        )
    )


settings = Settings()
