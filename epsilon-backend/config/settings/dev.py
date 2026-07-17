"""
Xporadia — Settings développement local
Usage : DJANGO_SETTINGS_MODULE=config.settings.dev
"""
from .base import *

DEBUG = True
SECRET_KEY = "dev-secret-key-not-for-production-epsilon-2025"

ALLOWED_HOSTS = ["*"]

# Base de données : SQLite par défaut (aucune config requise). Si vous avez
# déjà PostgreSQL en local, renseignez DATABASE_URL dans .env, par exemple :
#   DATABASE_URL=postgresql://epsilon_user:password@localhost:5432/epsilon_db
# et cette valeur sera utilisée à la place — aucun autre changement nécessaire.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db_dev.sqlite3'}")
}

# Cache local (mémoire) — pas besoin de Redis en dev
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Channel layers en mémoire pour le dev
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Celery en mode sync pour le dev
CELERY_TASK_ALWAYS_EAGER = True

# Emails dans la console en dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Debug Toolbar (optionnel)
CORS_ALLOW_ALL_ORIGINS = True

# Logs
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "DEBUG"},
}
