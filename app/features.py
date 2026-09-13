"""Construction du jeu de données supervisé (feature engineering).

Approche retenue (voir README, section "Choix technique") : un modèle
"1 pas" qui prédit l'état de la chambre à l'heure t+1 à partir :
- de l'état de la chambre à l'heure t (valeur courante + valeurs décalées
  1h/3h/6h/24h : `room_*_lag*`),
- de la météo extérieure à l'heure t (connue) et à l'heure t+1
  (`*_next`, connue à l'avance grâce aux prévisions),
- de features calendaires de l'heure cible (heure de la journée, jour de la
  semaine, mois, week-end).

Les prédictions à un horizon plus lointain (`FORECAST_HORIZON_HOURS`) sont
obtenues en ré-appliquant ce modèle heure par heure de façon récursive
(cf. `app.predict`) : la sortie prédite à t+1 sert d'entrée "courante" pour
prédire t+2, etc. C'est l'approche la plus simple et la plus robuste pour
démarrer avec peu de données (cf. choix du gradient boosting dans le README).

Note sur les valeurs décalées (`room_*_lag*`) : quand l'historique ne remonte
pas encore assez loin pour calculer un lag (ex. `lag24` avant 24h de mesures),
on retombe sur la valeur courante plutôt que de rejeter la ligne entière.
C'est exactement ce que fait déjà `build_inference_row` en prédiction ; le
faire aussi à l'entraînement évite d'exiger plusieurs jours de données avant
de pouvoir entraîner un premier modèle (voir `MIN_TRAINING_ROWS`).
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd

ROOM_VARS = ("temperature", "humidity", "pressure")
OUT_VARS = ("temperature", "humidity", "pressure", "cloud_cover", "wind_speed", "precipitation")
LAG_HOURS = (1, 3, 6, 24)
MAX_LAG_HOURS = max(LAG_HOURS)

ROOM_COLS = [f"room_{v}" for v in ROOM_VARS]
OUT_COLS = [f"out_{v}" for v in OUT_VARS]
OUT_NEXT_COLS = [f"{c}_next" for c in OUT_COLS]
LAG_COLS = [f"room_{v}_lag{lag}" for v in ROOM_VARS for lag in LAG_HOURS]
CALENDAR_COLS = ["hour", "day_of_week", "month", "is_weekend"]
TARGET_COLS = [f"target_{v}" for v in ROOM_VARS]

FEATURE_COLUMNS = ROOM_COLS + LAG_COLS + OUT_COLS + OUT_NEXT_COLS + CALENDAR_COLS


def _rows_to_frame(rows: Sequence, value_cols: Sequence[str]) -> pd.DataFrame:
    """Convertit une liste de sqlite3.Row (ou dicts) en DataFrame indexé par ts (UTC, horaire)."""
    data = [dict(r) for r in rows]
    df = pd.DataFrame(data, columns=["ts", *value_cols])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[list(value_cols)].astype(float)


def resample_room_hourly(room_rows: Sequence) -> pd.DataFrame:
    room = _rows_to_frame(room_rows, ROOM_VARS)
    return room.resample("1h").mean() if not room.empty else room


def resample_weather_hourly(weather_rows: Sequence) -> pd.DataFrame:
    weather = _rows_to_frame(weather_rows, OUT_VARS)
    return weather.resample("1h").mean() if not weather.empty else weather


def build_hourly_frame(room_rows: Sequence, weather_rows: Sequence) -> pd.DataFrame:
    """Rééchantillonne mesures chambre + météo à l'heure pleine et les aligne (jointure interne)."""
    room_hourly = resample_room_hourly(room_rows)
    weather_hourly = resample_weather_hourly(weather_rows)
    if room_hourly.empty or weather_hourly.empty:
        return pd.DataFrame()

    return room_hourly.add_prefix("room_").join(weather_hourly.add_prefix("out_"), how="inner")


def add_calendar_features(df: pd.DataFrame, target_index: pd.DatetimeIndex) -> pd.DataFrame:
    df = df.copy()
    df["hour"] = target_index.hour
    df["day_of_week"] = target_index.dayofweek
    df["month"] = target_index.month
    df["is_weekend"] = (target_index.dayofweek >= 5).astype(int)
    return df


def build_training_frame(room_rows: Sequence, weather_rows: Sequence) -> tuple[pd.DataFrame, list[str]]:
    """Construit le jeu de données d'entraînement complet (features + cibles), sans NaN.

    Renvoie (dataframe, liste ordonnée des colonnes de features).
    """
    merged = build_hourly_frame(room_rows, weather_rows)
    if merged.empty:
        return pd.DataFrame(), FEATURE_COLUMNS

    df = merged.copy()

    for col in ROOM_COLS:
        for lag in LAG_HOURS:
            # Repli sur la valeur courante si le lag n'est pas encore disponible
            # (voir la note en tête de fichier) : ne coûte que peu de précision
            # sur les toutes premières lignes, et évite de perdre 24h de données.
            df[f"{col}_lag{lag}"] = df[col].shift(lag).fillna(df[col])

    for col in OUT_COLS:
        df[f"{col}_next"] = df[col].shift(-1)

    for var in ROOM_VARS:
        df[f"target_{var}"] = df[f"room_{var}"].shift(-1)

    target_index = df.index + pd.Timedelta(hours=1)
    df = add_calendar_features(df, target_index)

    # Les lags sont désormais toujours renseignés (repli ci-dessus) ; seules
    # les colonnes météo décalées d'1h et la cible peuvent encore être NaN
    # (première/dernière heure de la plage disponible).
    required = OUT_COLS + OUT_NEXT_COLS + TARGET_COLS
    df = df.dropna(subset=required)

    return df, FEATURE_COLUMNS


def build_inference_row(
    room_state: dict[str, float],
    room_lags: dict[int, dict[str, float]],
    out_now: dict[str, float],
    out_next: dict[str, float],
    target_ts: pd.Timestamp,
) -> dict[str, float]:
    """Construit une seule ligne de features pour l'inférence récursive (voir app.predict).

    - `room_state` : valeurs courantes de la chambre (temperature/humidity/pressure) à t.
    - `room_lags` : dict {nb_heures: {temperature, humidity, pressure}} pour chaque lag requis.
    - `out_now` / `out_next` : météo (observée ou prévue) à t et t+1.
    - `target_ts` : horodatage de l'heure prédite (t+1), pour les features calendaires.
    """
    row: dict[str, float] = {}
    for var in ROOM_VARS:
        row[f"room_{var}"] = room_state[var]

    for lag in LAG_HOURS:
        lag_values = room_lags.get(lag, room_state)
        for var in ROOM_VARS:
            row[f"room_{var}_lag{lag}"] = lag_values[var]

    for var in OUT_VARS:
        row[f"out_{var}"] = out_now.get(var)
        row[f"out_{var}_next"] = out_next.get(var)

    row["hour"] = target_ts.hour
    row["day_of_week"] = target_ts.dayofweek
    row["month"] = target_ts.month
    row["is_weekend"] = int(target_ts.dayofweek >= 5)

    return row
