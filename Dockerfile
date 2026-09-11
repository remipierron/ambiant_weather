FROM python:3.11-slim

WORKDIR /app

# i2c-tools est utile pour debug (i2cdetect) directement dans le conteneur
# libgomp1 : runtime OpenMP requis par LightGBM (sinon "libgomp.so.1: cannot open shared object file")
RUN apt-get update && apt-get install -y --no-install-recommends \
    i2c-tools \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY lire_bme280.py .

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/meteo.db
ENV MODELS_DIR=/data/models

# Image commune aux 4 services (capteur, sync météo, entraînement, API) ;
# la commande réellement exécutée est fixée par service dans docker-compose.yml.
CMD ["python", "-m", "app.sensor"]
