"""Synchronisation périodique des données météo (Open-Meteo) vers la base.

Deux opérations :
1. Backfill (une fois, au premier démarrage si la base est vide) : télécharge
   l'historique météo réel depuis `WEATHER_HISTORY_START_DATE` jusqu'à
   aujourd'hui, par tranches d'un an (l'API accepte des plages plus larges,
   mais on découpe pour rester raisonnable en taille de réponse / mémoire).
2. Boucle périodique (toutes les `WEATHER_SYNC_INTERVAL_MINUTES`) : récupère
   la prévision courante (jusqu'à `FORECAST_DAYS` jours) ainsi que les
   `WEATHER_PAST_DAYS` derniers jours. La partie passée vient compléter
   `weather_observed` (l'archive historique a plusieurs jours de latence, ces
   données "quasi-observées" comblent le trou en attendant), la partie future
   est enregistrée telle quelle dans `weather_forecast`, horodatée par sa date
   d'émission (`issued_at`) pour pouvoir comparer plus tard prévision et
   réalité.

Utilisation :
    python -m app.weather_sync
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

from app.config import settings
from app.db import (
    get_latest_weather_observed_ts,
    init_db,
    insert_weather_forecast,
    upsert_weather_observed,
)
from app.weather_client import fetch_forecast, fetch_historical

logging.basicConfig(level=logging.INFO, format="%(asctime)s [weather] %(message)s")
logger = logging.getLogger(__name__)


def _daterange_chunks(start: date, end: date, chunk_days: int = 365):
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def backfill_history(force: bool = False) -> None:
    """Télécharge l'historique météo si la base ne contient encore rien."""
    if not force and get_latest_weather_observed_ts() is not None:
        logger.info("Historique météo déjà présent en base, backfill ignoré.")
        return

    start = datetime.strptime(settings.weather_history_start_date, "%Y-%m-%d").date()
    # L'archive a quelques jours de latence : on s'arrête à J-5 pour éviter
    # les réponses vides sur les jours les plus récents (la boucle de sync
    # périodique complète ensuite avec les données "quasi-observées").
    end = date.today() - timedelta(days=5)

    if start > end:
        logger.warning("Plage de backfill vide (start=%s > end=%s), rien à faire.", start, end)
        return

    total = 0
    for chunk_start, chunk_end in _daterange_chunks(start, end):
        records = fetch_historical(chunk_start.isoformat(), chunk_end.isoformat())
        total += upsert_weather_observed(records)
        logger.info("Backfill %s -> %s : %s lignes", chunk_start, chunk_end, len(records))
    logger.info("Backfill terminé : %s lignes météo au total.", total)


def sync_once() -> None:
    now = datetime.now(timezone.utc)
    now_iso_hour = now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")

    records = fetch_forecast()

    observed = [r for r in records if r["ts"] < now_iso_hour]
    upcoming = [r for r in records if r["ts"] >= now_iso_hour]

    n_observed = upsert_weather_observed(observed)
    n_forecast = insert_weather_forecast(now.isoformat(timespec="seconds"), upcoming)

    logger.info(
        "Sync météo : %s heures observées mises à jour, %s heures de prévision enregistrées (émises à %s).",
        n_observed,
        n_forecast,
        now.isoformat(timespec="seconds"),
    )


def run() -> None:
    init_db()
    backfill_history()

    interval = settings.weather_sync_interval_minutes * 60
    logger.info("Synchronisation météo toutes les %s minutes.", settings.weather_sync_interval_minutes)

    while True:
        try:
            sync_once()
        except Exception:
            logger.exception("Échec de la synchronisation météo, nouvel essai au prochain cycle.")
        time.sleep(interval)


if __name__ == "__main__":
    run()
