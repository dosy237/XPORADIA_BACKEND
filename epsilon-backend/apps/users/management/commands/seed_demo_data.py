import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.certification.models import (
    Certification,
    CertificationLevel,
    ExamAttempt,
    ModuleCategory,
    SessionStatus,
    TrainingModule,
    TrainingSession,
)
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

DEMO_TRAINER = {
    "email": "konan.trainer@xporadia.ci",
    "first_name": "Konan",
    "last_name": "Assi",
    "phone": "+2250700000005",
}

DEMO_MODULES = [
    {
        "title": "Fondamentaux pédagogiques",
        "category": ModuleCategory.PEDAGOGY,
        "description": "Bases de la pédagogie active et de la gestion d'une salle de classe.",
        "objectives": ["Maîtriser les méthodes actives", "Structurer une séquence pédagogique"],
        "duration_hours": 8,
        "price": 15000,
        "target_level": CertificationLevel.BRONZE,
    },
    {
        "title": "Éthique professionnelle",
        "category": ModuleCategory.ETHICS,
        "description": "Déontologie de l'enseignant et relation avec les familles.",
        "objectives": ["Connaître le cadre déontologique", "Gérer les situations sensibles"],
        "duration_hours": 6,
        "price": 12000,
        "target_level": CertificationLevel.BRONZE,
    },
    {
        "title": "Didactique disciplinaire",
        "category": ModuleCategory.DIDACTICS,
        "description": "Approfondissement des méthodes d'enseignement par discipline.",
        "objectives": ["Adapter sa didactique à la discipline", "Concevoir des évaluations pertinentes"],
        "duration_hours": 12,
        "price": 25000,
        "target_level": CertificationLevel.SILVER,
    },
    {
        "title": "Gestion de classe avancée",
        "category": ModuleCategory.MANAGEMENT,
        "description": "Techniques avancées de gestion de groupe et de discipline positive.",
        "objectives": ["Prévenir les conflits", "Animer une classe hétérogène"],
        "duration_hours": 10,
        "price": 22000,
        "target_level": CertificationLevel.SILVER,
    },
    {
        "title": "Leadership pédagogique",
        "category": ModuleCategory.LEADERSHIP,
        "description": "Devenir référent pédagogique au sein de son établissement.",
        "objectives": ["Encadrer des pairs", "Piloter un projet pédagogique d'établissement"],
        "duration_hours": 16,
        "price": 40000,
        "target_level": CertificationLevel.GOLD,
    },
]

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

            self._seed_certification_catalog()

        self.stdout.write(self.style.SUCCESS(f"\nMot de passe commun de démo : {DEMO_PASSWORD}"))

    def _seed_certification_catalog(self):
        trainer, created = User.objects.get_or_create(
            email=DEMO_TRAINER["email"],
            defaults={
                "first_name": DEMO_TRAINER["first_name"],
                "last_name": DEMO_TRAINER["last_name"],
                "phone": DEMO_TRAINER["phone"],
                "primary_role": UserRole.TRAINER,
                "is_verified": True,
                "is_documents_validated": True,
            },
        )
        if created:
            trainer.set_password(DEMO_PASSWORD)
            trainer.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Créé : {trainer.email} (trainer)"))

        modules = {}
        for data in DEMO_MODULES:
            module, created = TrainingModule.objects.get_or_create(
                title=data["title"], defaults=data
            )
            modules[module.title] = module
            if created:
                self.stdout.write(self.style.SUCCESS(f"Module créé : {module.title}"))

        upcoming_date = datetime.date.today() + datetime.timedelta(days=14)
        for title, module in modules.items():
            TrainingSession.objects.get_or_create(
                module=module,
                trainer=trainer,
                date=upcoming_date,
                defaults={
                    "city": "Abidjan",
                    "location": "Centre de formation Epsilon, Cocody",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "capacity": 25,
                    "status": SessionStatus.PLANNED,
                },
            )

        # Donne au professeur de démo une certification Bronze déjà obtenue,
        # pour illustrer un profil "en cours de progression" plutôt que vierge.
        teacher = User.objects.filter(email="awa.teacher@xporadia.ci").first()
        bronze_module = modules.get("Fondamentaux pédagogiques")
        if teacher and bronze_module and not Certification.objects.filter(
            teacher=teacher, module=bronze_module
        ).exists():
            session = TrainingSession.objects.filter(module=bronze_module, trainer=trainer).first()
            attempt = ExamAttempt.objects.create(
                teacher=teacher,
                session=session,
                score_total=88,
                status="graded",
            )
            Certification.objects.create(
                teacher=teacher,
                module=bronze_module,
                attempt=attempt,
                level=CertificationLevel.BRONZE,
                score_total=88,
                qr_code=f"XPO-CERT-{teacher.id}-BRONZE-DEMO",
                expires_at=datetime.date.today() + datetime.timedelta(days=730),
            )
            self.stdout.write(self.style.SUCCESS(f"Certification Bronze créée pour {teacher.email}"))
