"""Client HTTP minimal pour l'API Open-Meteo (gratuite, sans clé).

Deux endpoints utilisés :
- Historical Weather API (archive-api.open-meteo.com) : historique long
  (depuis 1940) utilisé pour le backfill initial.
- Forecast API (api.open-meteo.com) : prévisions jusqu'à 16 jours + données
  récentes des `past_days` derniers jours (utilisées comme "observé" en
  attendant que l'archive, qui a quelques jours de latence, les couvre).

Les deux renvoient un bloc `hourly` avec des tableaux parallèles (un par
variable). On les transforme ici en une liste de dicts, un par heure,
avec des noms de colonnes stables utilisés dans toute la base de données :
    ts, temperature, humidity, pressure, cloud_cover, wind_speed, precipitation
"""

from __future__ import annotations

import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Mapping variable Open-Meteo -> nom de colonne interne
_VARIABLE_MAP = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "surface_pressure": "pressure",
    "cloud_cover": "cloud_cover",
    "wind_speed_10m": "wind_speed",
    "precipitation": "precipitation",
}


def _parse_hourly_block(payload: dict) -> list[dict]:
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        return []

    times = hourly["time"]
    columns = {
        internal_name: hourly.get(om_name, [None] * len(times))
        for om_name, internal_name in _VARIABLE_MAP.items()
    }

    records = []
    for i, t in enumerate(times):
        # Open-Meteo renvoie des heures locales "naïves" au format ISO
        # (YYYY-MM-DDTHH:MM) quand on demande timezone=UTC : on les stocke
        # telles quelles, en heure UTC, avec les secondes ajoutées.
        ts = t if len(t) > 16 else f"{t}:00"
        record = {"ts": f"{ts}+00:00", "source": "open-meteo"}
        for internal_name, values in columns.items():
            record[internal_name] = values[i] if i < len(values) else None
        records.append(record)
    return records


def _get(url: str, params: dict) -> dict:
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_historical(
    start_date: str,
    end_date: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict]:
    """Récupère l'historique météo réel (archive) entre deux dates (YYYY-MM-DD incluses)."""
    params = {
        "latitude": latitude if latitude is not None else settings.latitude,
        "longitude": longitude if longitude is not None else settings.longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(_VARIABLE_MAP.keys()),
        "timezone": "UTC",
    }
    logger.info("Requête Open-Meteo (archive) %s -> %s", start_date, end_date)
    payload = _get(ARCHIVE_URL, params)
    return _parse_hourly_block(payload)


def fetch_forecast(
    forecast_days: int | None = None,
    past_days: int | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict]:
    """Récupère les prévisions à venir + les `past_days` derniers jours (quasi-observé)."""
    params = {
        "latitude": latitude if latitude is not None else settings.latitude,
        "longitude": longitude if longitude is not None else settings.longitude,
        "forecast_days": forecast_days if forecast_days is not None else settings.forecast_days,
        "past_days": past_days if past_days is not None else settings.past_days,
        "hourly": ",".join(_VARIABLE_MAP.keys()),
        "timezone": "UTC",
    }
    logger.info(
        "Requête Open-Meteo (forecast) : %s jours passés, %s jours à venir",
        params["past_days"],
        params["forecast_days"],
    )
    payload = _get(FORECAST_URL, params)
    return _parse_hourly_block(payload)
