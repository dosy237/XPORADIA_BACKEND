# ============================================================
# Epsilon Backend — Makefile
# Usage : make <commande>
# ============================================================

.PHONY: help install dev migrate shell test lint format clean

help:  ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Installe les dépendances de développement
	python -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements/dev.txt
	cp .env.example .env
	@echo "✅ Installation terminée. Éditez .env puis lancez 'make dev'"

dev:  ## Lance le serveur de développement
	venv/bin/python manage.py runserver 0.0.0.0:8000

migrate:  ## Applique les migrations
	venv/bin/python manage.py migrate

makemigrations:  ## Crée les migrations
	venv/bin/python manage.py makemigrations

shell:  ## Lance le shell Django
	venv/bin/python manage.py shell_plus

test:  ## Lance les tests avec couverture
	venv/bin/pytest

test-fast:  ## Lance les tests sans couverture
	venv/bin/pytest --no-cov -x

lint:  ## Vérifie le style du code
	venv/bin/flake8 apps/
	venv/bin/bandit -r apps/ -c pyproject.toml

format:  ## Formate le code (black + isort)
	venv/bin/black apps/
	venv/bin/isort apps/

docker-up:  ## Lance tous les services Docker
	docker compose up -d

docker-down:  ## Arrête tous les services Docker
	docker compose down

docker-logs:  ## Affiche les logs Docker
	docker compose logs -f api

clean:  ## Nettoie les fichiers générés
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf htmlcov/ .coverage coverage.xml
