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
RUN python manage.py collectstatic --noinput
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000
CMD ["gunicorn", "config.asgi:application", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
