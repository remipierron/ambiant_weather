"""Lecture en boucle du capteur BME280 (température / humidité / pression)
et écriture de chaque mesure dans la base SQLite partagée.

Reprend le script `lire_bme280.py` d'origine (bus I2C 1, adresse 0x77 par
défaut sur ce Raspberry Pi) en ajoutant :
- l'écriture en base (`app.db.insert_room_measurement`) au lieu du simple
  affichage,
- un mode simulation (`SENSOR_MOCK=true`) qui ne nécessite aucun matériel,
  utile en développement ou pour tester le reste de la chaîne.

Utilisation :
    python -m app.sensor
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

from app.config import settings
from app.db import init_db, insert_room_measurement

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sensor] %(message)s")
logger = logging.getLogger(__name__)


class SensorReading:
    __slots__ = ("temperature", "humidity", "pressure")

    def __init__(self, temperature: float, humidity: float, pressure: float):
        self.temperature = temperature
        self.humidity = humidity
        self.pressure = pressure


class MockSensor:
    """Génère des valeurs plausibles pour tester la chaîne sans capteur."""

    def __init__(self) -> None:
        self._temperature = 21.0
        self._humidity = 45.0
        self._pressure = 1015.0

    def sample(self) -> SensorReading:
        self._temperature += random.uniform(-0.05, 0.05)
        self._humidity = min(80.0, max(20.0, self._humidity + random.uniform(-0.3, 0.3)))
        self._pressure += random.uniform(-0.1, 0.1)
        return SensorReading(self._temperature, self._humidity, self._pressure)


class Bme280Sensor:
    """Enveloppe autour de smbus2 + RPi.bme280 (paquet PyPI, importé `bme280`)."""

    def __init__(self, port: int, address: int) -> None:
        import bme280  # import différé : uniquement nécessaire hors mode mock
        import smbus2

        self._bme280 = bme280
        self._bus = smbus2.SMBus(port)
        self._address = address
        self._calibration_params = bme280.load_calibration_params(self._bus, address)

    def sample(self) -> SensorReading:
        data = self._bme280.sample(self._bus, self._address, self._calibration_params)
        return SensorReading(data.temperature, data.humidity, data.pressure)


def build_sensor():
    if settings.sensor_mock:
        logger.info("Mode simulation activé (SENSOR_MOCK=true) : aucun capteur requis.")
        return MockSensor()
    return Bme280Sensor(settings.sensor_i2c_port, settings.sensor_i2c_address)


def run(sensor=None) -> None:
    init_db()
    sensor = sensor or build_sensor()

    logger.info(
        "Lecture du capteur BME280 toutes les %ss - Ctrl+C pour arrêter",
        settings.sensor_interval_seconds,
    )

    try:
        while True:
            reading = sensor.sample()
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

            insert_room_measurement(ts, reading.temperature, reading.humidity, reading.pressure)

            logger.info(
                "%s | Température : %6.2f °C | Humidité : %6.2f %% | Pression : %7.2f hPa",
                ts,
                reading.temperature,
                reading.humidity,
                reading.pressure,
            )

            time.sleep(settings.sensor_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Arrêt de la lecture.")


if __name__ == "__main__":
    run()
