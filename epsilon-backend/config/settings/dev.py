"""
Xporadia — Settings développement local
Usage : DJANGO_SETTINGS_MODULE=config.settings.dev
"""
from .base import *

DEBUG = True
SECRET_KEY = "dev-secret-key-not-for-production-epsilon-2025"

ALLOWED_HOSTS = ["*"]

# Base de données SQLite pour le dev local (pas besoin de PostgreSQL)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_dev.sqlite3",
    }
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
