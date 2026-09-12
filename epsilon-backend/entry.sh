#!/bin/sh
# Xporadia — entrypoint production. Applique les migrations et
# régénère les fichiers statiques à chaque démarrage de conteneur
# (jamais au moment du build de l'image, qui n'a pas accès à la base
# de données ni aux vraies variables d'environnement d'exécution),
# puis lance la commande transmise en argument (voir CMD du Dockerfile).
set -e

echo "[entry.sh] Migrations..."
python manage.py migrate --noinput

echo "[entry.sh] Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

echo "[entry.sh] Démarrage : $*"
exec "$@"
