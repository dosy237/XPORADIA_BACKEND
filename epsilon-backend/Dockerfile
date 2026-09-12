# ============================================================
# Epsilon Backend — Dockerfile
# Multi-stage build : dev léger, prod optimisé
# ============================================================
FROM python:3.12-slim AS base

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements/ requirements/
RUN pip install --no-cache-dir --upgrade pip

# ---- STAGE DEV ----
FROM base AS dev
RUN pip install --no-cache-dir -r requirements/dev.txt
COPY . .
ENV DJANGO_SETTINGS_MODULE=config.settings.dev
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---- STAGE PROD ----
FROM base AS prod
RUN pip install --no-cache-dir -r requirements/prod.txt
COPY . .
RUN chmod +x entry.sh
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 9110
ENTRYPOINT ["./entry.sh"]
# Daphne (déjà utilisé pour les WebSockets Channels) plutôt que
# gunicorn+uvicorn : uvicorn n'est pas dans requirements/, et daphne
# est le serveur ASGI de référence du projet — pas de dépendance en plus.
CMD ["daphne", "-b", "0.0.0.0", "-p", "9110", "config.asgi:application"]
