# ============================================================
# Epsilon Backend — Makefile
# Usage : make <commande>
# ============================================================

.PHONY: help install setup dev migrate makemigrations seed shell test test-fast lint format clean

help:  ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Installe les dépendances de développement
	python -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements/dev.txt
	cp .env.example .env
	@echo "✅ Installation terminée. Lancez maintenant 'make setup' puis 'make dev'"

setup:  ## Crée la base de données et la remplit avec des données de démo (à faire une fois après install)
	venv/bin/python manage.py migrate
	venv/bin/python manage.py seed_demo_data
	@echo "✅ Base de données prête, avec des comptes de démo. Voir SEED_DATA.md."

dev:  ## Lance le serveur de développement
	venv/bin/python manage.py runserver 0.0.0.0:8000

migrate:  ## Applique les migrations
	venv/bin/python manage.py migrate

makemigrations:  ## Crée les migrations
	venv/bin/python manage.py makemigrations

seed:  ## Remplit (ou re-remplit) la base avec le jeu de données de démo
	venv/bin/python manage.py seed_demo_data

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
