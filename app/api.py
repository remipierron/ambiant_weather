"""API FastAPI + tableau de bord exposant l'historique et les prédictions.

Endpoints JSON sous `/api/*`, tableau de bord HTML servi sur `/`.

Utilisation :
    uvicorn app.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import (
    get_latest_forecast_batch,
    get_latest_predictions,
    get_latest_room_measurement,
    get_room_measurements,
    get_weather_observed,
    init_db,
    rows_to_dicts,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Météo prévision chambre", version="1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}


@app.get("/api/latest")
def latest() -> dict:
    row = get_latest_room_measurement()
    if row is None:
        raise HTTPException(status_code=404, detail="Aucune mesure disponible.")
    return dict(row)


@app.get("/api/history")
def history(hours: int = 72) -> dict:
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    room = rows_to_dicts(get_room_measurements(start=start))
    weather = rows_to_dicts(get_weather_observed(start=start))
    return {"room": room, "weather": weather}


@app.get("/api/forecast")
def forecast() -> list[dict]:
    return rows_to_dicts(get_latest_forecast_batch())


@app.get("/api/predictions")
def predictions() -> list[dict]:
    return rows_to_dicts(get_latest_predictions())


@app.get("/api/metadata")
def metadata() -> dict:
    path = Path(settings.models_dir) / "metadata.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Aucun modèle entraîné pour le moment.")
    return json.loads(path.read_text())


@app.get("/")
def dashboard() -> FileResponse:
    """Page 1 — les 3 indicateurs relevés (température, humidité, pression)."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/previsions")
def previsions_page() -> FileResponse:
    """Page 2 — graphiques de prévisions (mesuré/prédit, observé/prévu)."""
    return FileResponse(STATIC_DIR / "previsions.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
