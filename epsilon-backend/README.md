# ε Xporadia — Backend

> Plateforme de certification professionnelle des enseignants du secteur privé africain.
> **Django REST Framework · PostgreSQL · Redis · Celery · Docker**

---

## Table des matières

- [Stack technique](#stack-technique)
- [Prérequis](#prérequis)
- [Installation locale](#installation-locale)
- [Structure du projet](#structure-du-projet)
- [Workflow Git & branches](#workflow-git--branches)
- [Convention de commits](#convention-de-commits)
- [Créer une feature](#créer-une-feature)
- [Tests](#tests)
- [Qualité du code](#qualité-du-code)
- [Variables d'environnement](#variables-denvironnement)
- [Déploiement](#déploiement)
- [Commandes utiles](#commandes-utiles)

---

## Stack technique

| Couche | Technologie | Version |
|---|---|---|
| Framework | Django + DRF | 5.0.6 / 3.15 |
| Base de données | PostgreSQL | 16 |
| Cache / Broker | Redis | 7 |
| Tâches async | Celery + Beat | 5.4 |
| WebSocket | Django Channels | 4.1 |
| Serveur prod | Gunicorn + Daphne | — |
| Storage | AWS S3 | — |
| PDF | WeasyPrint | 62.3 |
| Auth | JWT RS256 (simplejwt) | 5.3 |
| API Docs | drf-spectacular (OpenAPI) | 0.27 |

---

## Prérequis

```bash
Python >= 3.12
Git
Docker & Docker Compose (recommandé)
# ou : PostgreSQL 16 + Redis 7 en local
```

---

## Installation locale

### Option A — Docker (recommandée)

```bash
# 1. Cloner le repo
git clone git@github.com:ton-org/xporadia-backend.git
cd xporadia-backend

# 2. Copier les variables d'environnement
cp .env.example .env
# Éditez .env si nécessaire

# 3. Lancer tous les services
docker compose up -d

# 4. Vérifier que tout tourne
docker compose logs -f api
# → "Starting development server at http://0.0.0.0:8000/"
```

### Option B — Sans Docker

```bash
# 1. Cloner + créer l'environnement virtuel
git clone git@github.com:ton-org/xporadia-backend.git
cd xporadia-backend
python -m venv venv
source venv/bin/activate  # Windows : venv\Scripts\activate

# 2. Installer les dépendances
pip install -r requirements/dev.txt

# 3. Variables d'environnement
cp .env.example .env
# Éditez .env : DATABASE_URL, REDIS_URL, SECRET_KEY

# 4. Migrations + lancement
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

# 5. (Autre terminal) Celery worker
celery -A config worker --loglevel=info
```

**API disponible sur** : http://localhost:8000
**Documentation** : http://localhost:8000/api/docs/

---

## Structure du projet

```
xporadia-backend/
├── .github/
│   └── workflows/
│       ├── ci.yml          # Lint + tests sur chaque PR
│       └── deploy.yml      # Deploy staging (develop) + prod (main)
├── apps/
│   ├── users/              # EP-01 — Auth & profils multi-rôles
│   ├── certification/      # EP-02 — Certification (modules, examens, certificats)
│   ├── employment/         # EP-03 — Marché de l'emploi
│   ├── internships/        # EP-04 — Stages scolaires
│   ├── tutoring/           # EP-05 — Cours particuliers
│   ├── virtual_classes/    # EP-09 — Classes virtuelles
│   ├── library/            # EP-10 — Bibliothèque de ressources
│   ├── payments/           # EP-07 — Paiements Mobile Money
│   ├── notifications/      # EP-08 — Notifications push/SMS/email
│   └── admin_xporadia/      # EP-06 — Back-office administration
├── config/
│   ├── settings/
│   │   ├── base.py         # Settings communs
│   │   ├── dev.py          # Dev local (SQLite, LocMem cache)
│   │   ├── staging.py      # Staging (PostgreSQL, Redis, S3)
│   │   └── prod.py         # Production (sécurité renforcée)
│   ├── urls.py             # Routeur principal
│   ├── asgi.py             # WebSocket (Channels)
│   └── celery.py           # Configuration Celery
├── requirements/
│   ├── base.txt            # Dépendances communes
│   ├── dev.txt             # + pytest, black, flake8...
│   └── prod.txt            # + sentry
├── .env.example            # Template variables d'environnement
├── docker-compose.yml      # Stack complète dev (API + DB + Redis + Celery)
├── Dockerfile              # Multi-stage (dev / prod)
├── Makefile                # Commandes utilitaires
├── pytest.ini              # Config tests
├── pyproject.toml          # Black + isort
└── .pre-commit-config.yaml # Hooks automatiques
```

### Structure d'une app

```
apps/certification/
├── __init__.py
├── apps.py          # AppConfig
├── models.py        # Modèles Django (entités)
├── serializers.py   # DRF Serializers (validation + sérialisation)
├── views.py         # ViewSets DRF (logique métier)
├── urls.py          # Routes de l'app
├── admin.py         # Enregistrement Django Admin
├── permissions.py   # Permissions custom (créé à la feature)
├── filters.py       # Filtres django-filter (créé à la feature)
└── tests/
    ├── __init__.py
    ├── test_models.py
    └── test_views.py
```

---

## Workflow Git & branches

### Modèle de branches

```
main
 └── develop                    ← branche d'intégration
      └── feature/EP-02-US-02-01-catalogue-modules
      └── feature/EP-01-US-01-01-inscription-enseignant
      └── fix/EP-03-US-03-02-offre-publication-bug
```

| Branche | Rôle | Déploiement auto |
|---|---|---|
| `main` | Code stable — production | → Production (après MVP) |
| `develop` | Intégration de toutes les features | → Staging (automatique) |
| `feature/EP-XX-US-XX-XX-nom` | Une feature = une US Jira | — |
| `fix/EP-XX-nom` | Correction de bug | — |
| `hotfix/nom` | Correction urgente en prod | → Production direct |

### Règles

- **On ne push jamais directement sur `main` ou `develop`**
- **Toute feature passe par une Pull Request** (minimum 1 reviewer)
- **La CI doit passer** (lint + tests + coverage ≥ 80%) avant le merge
- **Une PR = une User Story** — granularité maximale

---

## Convention de commits

Format : **Conventional Commits** (https://www.conventionalcommits.org)

```
<type>(<scope>): <description courte>

[corps optionnel : contexte, pourquoi]

[footer : Closes #US-XX, Breaking changes]
```

### Types

| Type | Usage |
|---|---|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bug |
| `docs` | Documentation uniquement |
| `test` | Ajout ou modification de tests |
| `refactor` | Refactoring sans changement de comportement |
| `chore` | Maintenance (deps, config, CI) |
| `perf` | Amélioration de performance |
| `style` | Formatage, lint (pas de logique) |

### Exemples

```bash
git commit -m "feat(users): ajouter inscription enseignant avec OTP

- Formulaire email + téléphone + diplômes
- Vérification email par OTP 6 chiffres
- Upload carte d'identité (PDF/image)
- Statut 'en_attente' après inscription

Closes EP-01-US-01-01"

git commit -m "fix(certification): corriger le calcul de la note finale

La moyenne 50% présentiel + 50% examen était arrondie à l'excès.
Remplacement de round() par Decimal pour la précision.

Closes EP-02-US-02-04"

git commit -m "test(users): ajouter tests UserModel et inscription

- test_create_user_with_email
- test_user_multi_roles
- test_inscription_enseignant_otp
Coverage users : 94%"
```

---

## Créer une feature

### Étapes complètes (à suivre dans l'ordre)

```bash
# 1. Se placer sur develop et se mettre à jour
git checkout develop
git pull origin develop

# 2. Créer la branche de la feature
# Convention : feature/EP-{épique}-US-{story}-{description-courte}
git checkout -b feature/EP-01-US-01-01-inscription-enseignant

# 3. Créer le dossier de documentation de la feature
mkdir -p apps/users/docs/US-01-01-inscription-enseignant
# → Y placer :
#   - diagramme-activite.puml
#   - diagramme-sequence.puml
#   - notes-technique.md

# 4. Vérifier / écrire le model.py
# → python manage.py makemigrations
# → python manage.py migrate
# → python manage.py check

# 5. Écrire les tests AVANT le code (TDD recommandé)
# → apps/users/tests/test_views.py

# 6. Développer la feature
# → serializers.py → views.py → urls.py → admin.py

# 7. Lancer les tests
make test
# ou : pytest apps/users/

# 8. Vérifier la qualité
make lint
make format

# 9. Committer (messages Conventional Commits)
git add .
git commit -m "feat(users): inscription enseignant avec OTP"

# 10. Pousser et ouvrir une Pull Request vers develop
git push origin feature/EP-01-US-01-01-inscription-enseignant
# → Ouvrir la PR sur GitHub vers develop
# → Assigner un reviewer
# → Attendre le passage de la CI + la review
```

### Structure d'un dossier docs de feature

```
apps/users/docs/US-01-01-inscription-enseignant/
├── diagramme-activite.puml       # Flux d'activité (PlantUML)
├── diagramme-sequence.puml       # Séquence des échanges API
└── notes-technique.md            # Décisions techniques, edge cases
```

---

## Tests

```bash
# Lancer tous les tests
make test
# ou
pytest

# Tests d'une app spécifique
pytest apps/users/

# Tests d'un fichier
pytest apps/users/tests/test_views.py

# Tests sans couverture (plus rapide)
make test-fast

# Rapport HTML de couverture
pytest --cov=apps --cov-report=html
# → Ouvrir coverage_html/index.html
```

**Objectif couverture** : ≥ 80% par app, mesuré à chaque CI.

### Structure d'un test

```python
# apps/users/tests/test_views.py
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from apps.users.models import User, UserRole


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def enseignant(db):
    return User.objects.create_user(
        email="kouame@test.ci",
        password="testpass123",
        first_name="Kouamé",
        last_name="Test",
        primary_role=UserRole.TEACHER,
    )


@pytest.mark.django_db
class TestInscriptionEnseignant:
    def test_inscription_succes(self, api_client):
        url = reverse("users:register")
        data = {
            "email": "awa@test.ci",
            "password": "SecurePass123!",
            "first_name": "Awa",
            "last_name": "Diallo",
            "primary_role": "teacher",
            "phone": "+2250708000000",
        }
        response = api_client.post(url, data)
        assert response.status_code == 201
        assert User.objects.filter(email="awa@test.ci").exists()

    def test_inscription_email_duplique(self, api_client, enseignant):
        url = reverse("users:register")
        data = {"email": "kouame@test.ci", "password": "test123"}
        response = api_client.post(url, data)
        assert response.status_code == 400
```

---

## Qualité du code

```bash
# Vérifier le formatage (black)
black --check apps/

# Formater le code
black apps/

# Vérifier l'ordre des imports (isort)
isort --check-only apps/

# Corriger les imports
isort apps/

# Lint (flake8)
flake8 apps/

# Audit de sécurité (bandit)
bandit -r apps/ -c pyproject.toml

# Tout en une commande
make lint      # vérification
make format    # correction automatique
```

### Pre-commit (automatique)

```bash
# Installation (une seule fois)
pre-commit install

# → Désormais, à chaque git commit :
# black, isort, flake8, bandit s'exécutent automatiquement
# Le commit est bloqué si une règle échoue
```

---

## Variables d'environnement

Copier `.env.example` en `.env` et renseigner les valeurs :

| Variable | Dev | Description |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | Module settings actif |
| `SECRET_KEY` | (générer) | Clé secrète Django |
| `DATABASE_URL` | `sqlite:///db_dev.sqlite3` | URL base de données |
| `REDIS_URL` | `redis://localhost:6379/0` | URL Redis |
| `CINETPAY_API_KEY` | — | Clé API CinetPay |
| `FCM_SERVER_KEY` | — | Firebase Cloud Messaging |
| `TWILIO_ACCOUNT_SID` | — | SMS via Twilio |
| `SENDGRID_API_KEY` | — | Emails via SendGrid |
| `SENTRY_DSN` | — | Monitoring Sentry |
| `AWS_ACCESS_KEY_ID` | — | AWS S3 |

> ⚠️ **Ne jamais committer `.env`** — il est dans `.gitignore`

---

## Déploiement

### Staging (automatique)

Chaque merge sur `develop` déclenche automatiquement le déploiement sur staging via GitHub Actions.

### Production (automatique — après MVP)

Chaque merge sur `main` déclenche le déploiement en production avec blue-green deployment et rollback automatique si le taux d'erreur dépasse 5%.

### Secrets GitHub à configurer

Dans `Settings > Secrets and variables > Actions` de votre repo :

```
STAGING_HOST         → IP du serveur staging
STAGING_USER         → User SSH
STAGING_SSH_KEY      → Clé SSH privée

PROD_HOST            → IP du serveur production
PROD_USER            → User SSH
PROD_SSH_KEY         → Clé SSH privée
```

---

## Commandes utiles

```bash
make help              # Voir toutes les commandes disponibles

make install           # Installation complète (venv + deps + .env)
make dev               # Lancer le serveur de dev
make migrate           # Appliquer les migrations
make makemigrations    # Créer les migrations
make shell             # Django shell interactif
make test              # Tests avec couverture
make test-fast         # Tests rapides (sans couverture)
make lint              # Vérification qualité
make format            # Formatage automatique
make docker-up         # Lancer Docker Compose
make docker-down       # Arrêter Docker Compose
make docker-logs       # Logs de l'API
make clean             # Nettoyer les fichiers générés
```

---

## Équipe & contact

Projet **Xporadia** — Confidentiel
Chef de projet : DONFACK Synthia Calorine
Stack : Django · React · React Native
Méthodologie : Agile Scrum · Jira · GitHub Flow
