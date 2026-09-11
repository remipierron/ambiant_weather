"""Point d'entrée historique pour la lecture du capteur BME280.

La logique complète (lecture + écriture en base SQLite + mode simulation)
vit maintenant dans `app/sensor.py`. Ce fichier est conservé comme point
d'entrée simple, utilisable directement :

    python lire_bme280.py

Pré-requis (voir aussi README.md) :
    sudo apt update
    sudo apt install -y python3-smbus2 i2c-tools
    pip install -r requirements.txt

Vérifier que le capteur est bien détecté avant de lancer ce script :
    i2cdetect -y 1
    -> doit afficher une adresse 0x76 ou 0x77
"""

from app.sensor import run

if __name__ == "__main__":
    run()
