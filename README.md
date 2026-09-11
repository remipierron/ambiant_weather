# Prédiction météo de chambre

## Objectif

Concevoir un système capable de prédire la température, l'humidité et la pression d'une chambre, en se basant sur :
- l'historique des données mesurées dans la chambre,
- l'historique météo passé,
- les prévisions météo futures.

## Architecture prévue

- **Capteur** : BME280 (température / humidité / pression), en I2C
- **Hébergement** : Raspberry Pi 5 (16 Go RAM), boîtier db-tronic avec HAT M.2 NVMe
- **Source météo externe** : API open source (à choisir)
- **Encapsulation** : le code de lecture du capteur tourne dans un conteneur Docker
- **Prédiction** : modèle de machine learning (à définir), entraîné sur l'historique croisé chambre + météo

## Avancement actuel

### ✅ Étape 1 — Lecture du capteur BME280 (terminée)

**Câblage**

Le capteur possède 6 broches (VCC, GND, CS, MISO/ADDR, SDA/MOSI, SCL/SCK), lues directement sur la sérigraphie du PCB. Branché sur le header GPIO du Raspberry Pi 5 (accessible en passthrough malgré le HAT M.2, via les fentes d'aération du boîtier) :

| Fil | Fonction | Broche GPIO (J8) |
|---|---|---|
| Rouge | VCC | Pin 1 (3.3V) |
| Noir | GND | Pin 6 (GND) |
| Jaune | SDA | Pin 3 (GPIO2) |
| Bleu | SCL | Pin 5 (GPIO3) |
| Vert/sarcelle | CS | Pin 17 (3.3V, force le mode I2C) |
| Orange | MISO/ADDR | Non connecté (inutile en I2C) |

**Difficultés rencontrées et résolues**

1. Le capteur n'était pas détecté (`i2cdetect -y 1` → erreur "No such file or directory") → l'I2C n'était pas activé.
2. Après activation via `raspi-config`, les bus détectés (`i2c-13`, `i2c-14`) ne correspondaient en fait à rien de connecté sur le header — fausse piste.
3. Cause racine trouvée avec `pinctrl get 2/3` : les broches GPIO2/GPIO3 n'avaient aucune fonction I2C assignée (`GPIO2 = none`).
4. La ligne `dtparam=i2c_arm=on` était présente dans `/boot/firmware/config.txt` mais **commentée** (`#`) → décommentée manuellement.
5. Après redémarrage, le vrai bus I2C (`i2c-1`, contrôleur Synopsys DesignWare) est apparu, avec le capteur détecté à l'adresse **0x77**.
6. Deux erreurs de câblage corrigées en cours de route (fil orange à la place du jaune, fil CS oublié).

**Script de lecture**

`lire_bme280.py` : lit en boucle température, humidité et pression via `smbus2` + `RPi.bme280` (le paquet PyPI `bme280` seul ne convient pas, son API a changé — il faut spécifiquement `RPi.bme280`).

**Conteneurisation Docker**

- `Dockerfile` : image `python:3.11-slim`, installe `i2c-tools` + dépendances Python, `ENV PYTHONUNBUFFERED=1` (indispensable, sinon les logs n'apparaissent pas en temps réel dans Docker).
- `docker-compose.yml` : monte `/dev/i2c-1` dans le conteneur pour lui donner accès au bus I2C de l'hôte.
- Déployé et testé avec succès sur le Raspberry Pi (dossier `~/docker/app3`) : lecture en continu confirmée (~24,5 °C / 35 % / 1018 hPa).

### ✅ Étape 2 — Historique et stockage (terminée)

- Base **SQLite** (`app/db.py`), un seul fichier partagé entre les 4 services via un volume Docker, mode WAL activé pour les accès concurrents.
- Le script de lecture (`app/sensor.py`, appelé par `lire_bme280.py`) écrit désormais chaque mesure en base (table `room_measurements`) au lieu de se contenter de l'afficher.
- Mode simulation (`SENSOR_MOCK=true`) pour développer/tester sans capteur branché.

### ✅ Étape 3 — Intégration météo externe (terminée)

- Client **Open-Meteo** (`app/weather_client.py`) : Historical Weather API pour le backfill, Forecast API pour les prévisions + les derniers jours écoulés.
- Service `weather-sync` (`app/weather_sync.py`) : backfill automatique de l'historique au premier démarrage (depuis `WEATHER_HISTORY_START_DATE`), puis synchronisation périodique (`WEATHER_SYNC_INTERVAL_MINUTES`) qui alimente `weather_observed` (météo réelle/quasi-réelle) et `weather_forecast` (prévisions telles qu'émises, horodatées par leur date d'émission).

### ✅ Étape 4 — Modèle de prédiction (terminée)

- **Feature engineering** (`app/features.py`) : modèle "1 pas" prédisant l'état de la chambre à t+1 à partir de l'état courant + valeurs décalées (1h/3h/6h/24h), de la météo extérieure à t et t+1 (connue à l'avance via les prévisions), et de features calendaires (heure, jour de semaine, mois, week-end).
- **Entraînement** (`app/train.py`) : régression linéaire (baseline) + gradient boosting **LightGBM** (modèle retenu) par variable, découpage train/test chronologique, métriques MAE/RMSE sauvegardées à côté des modèles.
- **Prédiction multi-heures** (`app/predict.py`) : application récursive du modèle 1-pas jusqu'à `FORECAST_HORIZON_HOURS` (48h par défaut) — la sortie prédite à t+1 sert d'entrée pour prédire t+2, etc.
- **Exposition** (`app/api.py`) : API FastAPI (`/api/latest`, `/api/history`, `/api/forecast`, `/api/predictions`, `/api/metadata`) + tableau de bord HTML (`/`) avec graphiques température/humidité/pression (mesuré vs prédit, extérieur observé vs prévu).
- Orchestration en boucle (`app/train_loop.py`) : ré-entraînement toutes les `TRAIN_INTERVAL_HOURS` (24h par défaut), régénération des prédictions toutes les `PREDICT_INTERVAL_MINUTES` (30 min par défaut).

## Architecture logicielle (services Docker)

Une unique image (`Dockerfile`) contenant tout le code Python, déclinée en 4 services (`docker-compose.yml`) partageant un volume `meteo-data` (base SQLite + modèles) :

| Service | Commande | Rôle |
|---|---|---|
| `sensor` | `python -m app.sensor` | Lecture BME280 en boucle -> `room_measurements` |
| `weather-sync` | `python -m app.weather_sync` | Backfill + synchronisation Open-Meteo -> `weather_observed` / `weather_forecast` |
| `trainer` | `python -m app.train_loop` | Ré-entraînement périodique + génération des prédictions -> `predictions` |
| `api` | `uvicorn app.api:app` | API + tableau de bord, port `8000` |

## Lancer le projet

1. Copier/adapter la configuration si besoin :
   ```bash
   cp .env.example .env   # déjà rempli avec la localisation de la chambre (Niort)
   ```
2. Démarrer tous les services :
   ```bash
   docker compose up -d --build
   ```
3. Tableau de bord accessible sur `http://<ip-du-pi>:8000/`.

Au premier démarrage : le backfill météo (plusieurs années d'historique) peut prendre quelques minutes, et l'entraînement ne se déclenche qu'une fois `MIN_TRAINING_ROWS` heures de données croisées chambre+météo disponibles (par défaut 72h) — en attendant, le tableau de bord affiche l'historique sans prédiction.

### Développement / tests en local (sans Raspberry Pi)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest httpx  # pour les tests

# Lire le capteur en mode simulation (pas de matériel requis)
SENSOR_MOCK=true python -m app.sensor

# Lancer l'API seule (avec DB_PATH par défaut ./data/meteo.db)
uvicorn app.api:app --reload

# Tests unitaires + test d'intégration (features, DB, entraînement/prédiction bout-en-bout)
pytest tests/ -q
```

## Choix technique : source de données et modèle

### Source de données météo : Open-Meteo

**Open-Meteo** retenu comme source météo externe :

- Gratuit sans clé API pour un usage non-commercial
- Historique disponible depuis 1940 (Historical Weather API) — idéal pour entraîner un modèle
- Prévisions jusqu'à 16 jours, mise à jour horaire
- Historical Forecast API : archive aussi les prévisions telles qu'émises à l'époque (utile pour évaluer la fiabilité de nos propres prédictions plus tard)
- API REST simple en JSON, wrapper Python disponible (`openmeteopy`) si besoin

Alternatives écartées (OpenWeatherMap, Weatherbit...) : nécessitent une clé API et ont des quotas gratuits plus restrictifs sur l'historique.

### Type de modèle : gradient boosting (LightGBM / XGBoost)

Modèle retenu pour démarrer : **gradient boosting sur variables tabulaires**, plutôt qu'un réseau de neurones.

**Pourquoi :**
- Le problème est une régression tabulaire avec features engineerées (température extérieure actuelle/prévue, heure de la journée, jour de la semaine, valeurs décalées des mesures précédentes...), pas une séquence brute — les gradient boosted trees excellent sur ce type de données
- Tourne bien sur Raspberry Pi (pas de GPU nécessaire, entraînement rapide)
- Facile à ré-entraîner régulièrement au fil de l'accumulation de données
- Interprétable (importance des features visible)

**Écarté pour l'instant :** LSTM / réseaux de neurones récurrents — ont besoin de beaucoup de données pour surpasser un modèle plus simple, plus lourds à entraîner sur un Pi, peu de bénéfice attendu vu le volume de données de départ.

**Point de départ recommandé :** une régression linéaire multiple comme baseline (température intérieure ≈ fonction linéaire de la température extérieure avec décalage temporel). Sert de référence honnête pour juger si le gradient boosting apporte un vrai gain.


## Fichiers du projet

- `lire_bme280.py` — point d'entrée historique du script de lecture du capteur (délègue à `app/sensor.py`)
- `app/config.py` — configuration centralisée (variables d'environnement)
- `app/db.py` — accès SQLite (schéma, lecture/écriture des 4 tables)
- `app/sensor.py` — lecture en boucle du BME280 -> DB (+ mode simulation)
- `app/weather_client.py` — client Open-Meteo (historique + prévisions)
- `app/weather_sync.py` — backfill + synchronisation météo périodique -> DB
- `app/features.py` — feature engineering (jeu de données supervisé)
- `app/train.py` — entraînement des modèles (baseline + LightGBM)
- `app/train_loop.py` — boucle ré-entraînement + prédiction
- `app/predict.py` — génération des prédictions multi-heures (récursif)
- `app/api.py` + `app/static/` — API FastAPI + tableau de bord
- `tests/` — tests unitaires (features, DB) et test d'intégration bout-en-bout
- `Dockerfile` — image commune aux 4 services
- `docker-compose.yml` — orchestration des 4 services + volume partagé
- `.env` / `.env.example` — configuration (localisation, intervalles, chemins)
- `requirements.txt` — dépendances Python