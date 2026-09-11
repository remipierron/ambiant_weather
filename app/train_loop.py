"""Boucle périodique : ré-entraînement des modèles puis génération des prédictions.

Tourne dans son propre conteneur (`trainer`), indépendant du capteur et de la
synchronisation météo, avec un cycle plus espacé (`TRAIN_INTERVAL_HOURS`,
24h par défaut) puisque le ré-entraînement complet est plus coûteux qu'une
simple inférence. Les prédictions, elles, sont régénérées plus souvent
(`PREDICT_INTERVAL_MINUTES`) avec le dernier modèle disponible, pour rester
à jour avec les toutes dernières prévisions météo.

Utilisation :
    python -m app.train_loop
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.db import init_db
from app.predict import ModelsNotReady, generate_predictions
from app.train import train_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s [train_loop] %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    init_db()

    train_interval = settings.train_interval_hours * 3600
    predict_interval = settings.predict_interval_minutes * 60

    last_train = 0.0

    while True:
        now = time.monotonic()

        if now - last_train >= train_interval:
            try:
                train_all()
            except Exception:
                logger.exception("Échec de l'entraînement, nouvel essai au prochain cycle.")
            last_train = now

        try:
            generate_predictions()
        except ModelsNotReady as exc:
            logger.info("Prédiction reportée : %s", exc)
        except Exception:
            logger.exception("Échec de la génération des prédictions.")

        time.sleep(predict_interval)


if __name__ == "__main__":
    run()
