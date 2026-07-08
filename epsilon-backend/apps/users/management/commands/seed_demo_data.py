from django.core.management.base import BaseCommand
from django.db import transaction

from apps.users.models import (
    Child,
    CompanyProfile,
    DirectorProfile,
    ParentProfile,
    TeacherProfile,
    User,
    UserRole,
)

DEMO_PASSWORD = "Xporadia2026!"

DEMO_USERS = [
    {
        "role": UserRole.TEACHER,
        "email": "awa.teacher@xporadia.ci",
        "first_name": "Awa",
        "last_name": "Bamba",
        "phone": "+2250700000001",
        "profile": {
            "subjects": ["Mathématiques", "Physique-Chimie"],
            "experience_years": 6,
            "hourly_rate": "6000",
            "location": "Yopougon, Abidjan",
            "bio": "Enseignante de sciences passionnée, pédagogie active et suivi personnalisé.",
            "available_for_tutoring": True,
            "available_for_employment": True,
        },
    },
    {
        "role": UserRole.DIRECTOR,
        "email": "kouassi.director@xporadia.ci",
        "first_name": "Kouassi",
        "last_name": "N'Guessan",
        "phone": "+2250700000002",
        "profile": {
            "school_name": "Groupe Scolaire La Réussite",
            "address": "Cocody, Abidjan",
            "levels_taught": ["Primaire", "Collège"],
            "student_count": 420,
            "is_partner": True,
        },
    },
    {
        "role": UserRole.PARENT,
        "email": "fatou.parent@xporadia.ci",
        "first_name": "Fatou",
        "last_name": "Traoré",
        "phone": "+2250700000003",
        "profile": {
            "location": "Marcory, Abidjan",
            "subscription_active": True,
        },
        "children": [
            {"first_name": "Aïcha", "class_level": "5ème", "target_subjects": ["Anglais", "Maths"]},
            {"first_name": "Ibrahim", "class_level": "CM2", "target_subjects": ["Français"]},
        ],
    },
    {
        "role": UserRole.COMPANY,
        "email": "contact.entreprise@xporadia.ci",
        "first_name": "Serge",
        "last_name": "Kouadio",
        "phone": "+2250700000004",
        "profile": {
            "company_name": "Ivoire Digital Solutions",
            "sector": "Technologies de l'éducation",
            "address": "Plateau, Abidjan",
            "is_partner": False,
        },
    },
]


class Command(BaseCommand):
    help = "Crée des comptes de démonstration (un par rôle) avec profils réalistes, déjà vérifiés."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime les comptes de démo existants avant de les recréer.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            deleted, _ = User.objects.filter(
                email__in=[u["email"] for u in DEMO_USERS]
            ).delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f"{deleted} enregistrement(s) de démo supprimé(s)."))

        with transaction.atomic():
            for entry in DEMO_USERS:
                if User.objects.filter(email=entry["email"]).exists():
                    self.stdout.write(f"Déjà présent, ignoré : {entry['email']}")
                    continue

                user = User.objects.create_user(
                    email=entry["email"],
                    password=DEMO_PASSWORD,
                    first_name=entry["first_name"],
                    last_name=entry["last_name"],
                    phone=entry["phone"],
                    primary_role=entry["role"],
                    is_verified=True,
                    is_documents_validated=True,
                )

                if entry["role"] == UserRole.TEACHER:
                    TeacherProfile.objects.create(user=user, **entry["profile"])
                elif entry["role"] == UserRole.DIRECTOR:
                    DirectorProfile.objects.create(user=user, **entry["profile"])
                elif entry["role"] == UserRole.COMPANY:
                    CompanyProfile.objects.create(user=user, **entry["profile"])
                elif entry["role"] == UserRole.PARENT:
                    parent_profile = ParentProfile.objects.create(user=user, **entry["profile"])
                    for child in entry.get("children", []):
                        Child.objects.create(parent=parent_profile, **child)

                self.stdout.write(self.style.SUCCESS(f"Créé : {entry['email']} ({entry['role']})"))

        self.stdout.write(self.style.SUCCESS(f"\nMot de passe commun de démo : {DEMO_PASSWORD}"))
