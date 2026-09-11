"""Logiciel de prédiction météo de chambre.

Sous-modules :
- config       : configuration centralisée (variables d'environnement)
- db           : accès SQLite (mesures capteur, météo, prédictions)
- sensor       : lecture en boucle du capteur BME280 -> DB
- weather_client : client HTTP pour l'API Open-Meteo
- weather_sync : synchronisation périodique historique + prévisions -> DB
- features     : construction du jeu de données supervisé (feature engineering)
- train        : entraînement des modèles (baseline + gradient boosting)
- train_loop   : ré-entraînement + génération de prédictions en boucle
- predict      : génération des prédictions à partir des derniers modèles
- api          : API FastAPI + tableau de bord exposant les prédictions
"""
