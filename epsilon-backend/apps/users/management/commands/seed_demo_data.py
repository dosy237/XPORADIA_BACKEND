import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Department, Enrollment, SchoolClass, Subject, Track
from apps.certification.models import (
    Certification,
    CertificationLevel,
    ExamAttempt,
    ExamQuestion,
    ModuleCategory,
    QuestionType,
    SessionEnrollment,
    SessionStatus,
    TrainingModule,
    TrainingSession,
)
from apps.employment.models import (
    ApplicationStatus,
    ContractType,
    JobApplication,
    JobListing,
    JobSeekingRequest,
    JobStatus,
    Recruitment,
)
from apps.internships.models import (
    ConventionStatus,
    InternshipApplication,
    InternshipApplicationStatus,
    InternshipConvention,
    InternshipEvaluation,
    InternshipJournal,
    InternshipLevel,
    InternshipOffer,
)
from apps.library.models import LibraryResource, ModerationStatus, ResourceType, SchoolLevel
from apps.notifications.services import notify_user
from apps.notifications.models import NotificationType
from apps.payments.models import MobileOperator, Payment, PaymentStatus, PaymentType
from apps.tutoring.models import TutoringReview, TutoringSession, TutoringSessionStatus
from apps.users.models import (
    Child,
    CompanyProfile,
    DirectorProfile,
    ParentProfile,
    TeacherProfile,
    User,
    UserRole,
)
from apps.virtual_classes.models import Exercise, ExerciseStatus, Submission, VirtualClass

DEMO_PASSWORD = "Xporadia2026!"
TODAY = datetime.date.today
CERT_VALIDITY_DAYS = 730


def _payment(user, amount, payment_type, status, content_object=None, operator=MobileOperator.ORANGE):
    payment = Payment.objects.create(
        user=user,
        amount=amount,
        operator=operator,
        phone_number="0700000000",
        payment_type=payment_type,
        status=status,
        tx_ref=f"XPO-DEMO-{User.objects.count()}-{Payment.objects.count()}-{amount}",
        content_object=content_object,
        completed_at=timezone.now() if status == PaymentStatus.COMPLETED else None,
    )
    return payment


class Command(BaseCommand):
    help = (
        "Peuple la base avec un jeu de données de démonstration complet et cohérent : "
        "établissements, classes, enseignants, parents/enfants, entreprises, offres "
        "d'emploi et de stage, cours particuliers, bibliothèque, certifications — "
        "de quoi tester chaque fonctionnalité de l'application sans rien créer à la main."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime tous les comptes @xporadia.ci de démo avant de les recréer.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            demo_users = User.objects.filter(email__endswith="@xporadia.ci")
            # Certification.attempt et TrainingSession.trainer sont en PROTECT :
            # il faut supprimer ces enregistrements avant les User eux-mêmes,
            # sans quoi Django refuse la suppression (ProtectedError).
            Certification.objects.filter(teacher__in=demo_users).delete()
            TrainingSession.objects.filter(trainer__in=demo_users).delete()
            deleted, _ = demo_users.delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f"{deleted} enregistrement(s) de démo supprimé(s)."))

        with transaction.atomic():
            users = self._seed_users()
            modules = self._seed_certification_catalog(users)
            self._seed_certifications(users, modules)
            establishments = self._seed_academics(users)
            self._seed_virtual_classes(establishments, users)
            self._seed_library(establishments, users)
            self._seed_employment(users)
            self._seed_internships(users, establishments)
            self._seed_tutoring(users)
            self._seed_training_enrollment(users, modules)

        self.stdout.write(self.style.SUCCESS(f"\nJeu de données de démonstration prêt."))
        self.stdout.write(self.style.SUCCESS(f"Mot de passe commun de démo : {DEMO_PASSWORD}"))
        self.stdout.write("Voir SEED_DATA.md à la racine du dépôt pour la liste complète des comptes.")

    # ------------------------------------------------------------------
    # Utilisateurs et profils
    # ------------------------------------------------------------------
    def _get_or_create_user(self, email, role, first_name, last_name, phone="", **extra):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "primary_role": role,
                "is_verified": True,
                "is_documents_validated": True,
                **extra,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Créé : {email} ({role})"))
        return user, created

    def _seed_users(self):
        users = {}

        # --- Enseignants (profils variés : niveaux, disponibilités) ---
        awa, _ = self._get_or_create_user(
            "awa.teacher@xporadia.ci", UserRole.TEACHER, "Awa", "Bamba", "+2250700000001"
        )
        TeacherProfile.objects.get_or_create(
            user=awa,
            defaults=dict(
                subjects=["Mathématiques", "Physique-Chimie"], experience_years=6, hourly_rate="6000",
                location="Yopougon, Abidjan",
                bio="Enseignante de sciences passionnée, pédagogie active et suivi personnalisé.",
                available_for_tutoring=True, available_for_employment=True,
            ),
        )

        yao, _ = self._get_or_create_user(
            "yao.teacher@xporadia.ci", UserRole.TEACHER, "Yao", "Kouassi", "+2250700000006"
        )
        TeacherProfile.objects.get_or_create(
            user=yao,
            defaults=dict(
                subjects=["Anglais"], experience_years=9, hourly_rate="7000", location="Cocody, Abidjan",
                bio="Professeur d'anglais, titulaire de classe depuis 4 ans.",
                available_for_tutoring=True, available_for_employment=False,
            ),
        )

        aminata, _ = self._get_or_create_user(
            "aminata.teacher@xporadia.ci", UserRole.TEACHER, "Aminata", "Diarra", "+2250700000007"
        )
        TeacherProfile.objects.get_or_create(
            user=aminata,
            defaults=dict(
                subjects=["SVT", "Mathématiques"], experience_years=12, hourly_rate="8500",
                location="Marcory, Abidjan", bio="Formatrice certifiée niveau Or, ouverte au recrutement.",
                available_for_tutoring=True, available_for_employment=True,
            ),
        )

        ibrahim, _ = self._get_or_create_user(
            "ibrahim.teacher@xporadia.ci", UserRole.TEACHER, "Ibrahim", "Fofana", "+2250700000008"
        )
        TeacherProfile.objects.get_or_create(
            user=ibrahim,
            defaults=dict(
                subjects=["Français"], experience_years=3, location="Abobo, Abidjan",
                bio="Jeune enseignant de primaire, titulaire de classe.",
                available_for_tutoring=False, available_for_employment=True,
            ),
        )

        mariam, _ = self._get_or_create_user(
            "mariam.teacher@xporadia.ci", UserRole.TEACHER, "Mariam", "Coulibaly", "+2250700000009"
        )
        TeacherProfile.objects.get_or_create(
            user=mariam,
            defaults=dict(
                subjects=["Mathématiques"], experience_years=5, location="Cocody, Abidjan",
                bio="Enseignante dédiée, corrections rapides et feedback détaillé.",
                available_for_tutoring=False, available_for_employment=True,
            ),
        )

        # --- Directeurs / établissements ---
        kouassi, _ = self._get_or_create_user(
            "kouassi.director@xporadia.ci", UserRole.DIRECTOR, "Kouassi", "N'Guessan", "+2250700000002"
        )
        DirectorProfile.objects.get_or_create(
            user=kouassi,
            defaults=dict(
                school_name="Groupe Scolaire La Réussite", address="Cocody, Abidjan",
                levels_taught=["Primaire", "Collège"], student_count=420, is_partner=True,
            ),
        )

        adjoua, _ = self._get_or_create_user(
            "adjoua.director@xporadia.ci", UserRole.DIRECTOR, "Adjoua", "Kone", "+2250700000010"
        )
        DirectorProfile.objects.get_or_create(
            user=adjoua,
            defaults=dict(
                school_name="Institution Sainte Marie", address="Yopougon, Abidjan",
                levels_taught=["Collège", "Lycée"], student_count=610, is_partner=False,
            ),
        )

        # --- Parents et enfants ---
        fatou, _ = self._get_or_create_user(
            "fatou.parent@xporadia.ci", UserRole.PARENT, "Fatou", "Traoré", "+2250700000003"
        )
        fatou_profile, _ = ParentProfile.objects.get_or_create(
            user=fatou, defaults=dict(location="Marcory, Abidjan", subscription_active=True)
        )
        aicha, _ = Child.objects.get_or_create(
            parent=fatou_profile, first_name="Aïcha",
            defaults=dict(class_level="5ème", target_subjects=["Anglais", "Maths"]),
        )
        ibrahim_child, _ = Child.objects.get_or_create(
            parent=fatou_profile, first_name="Ibrahim Jr",
            defaults=dict(class_level="CM2", target_subjects=["Français"]),
        )

        aya, _ = self._get_or_create_user(
            "aya.parent@xporadia.ci", UserRole.PARENT, "Aya", "Bamba", "+2250700000011"
        )
        aya_profile, _ = ParentProfile.objects.get_or_create(
            user=aya, defaults=dict(location="Cocody, Abidjan", subscription_active=False)
        )
        kouadio, _ = Child.objects.get_or_create(
            parent=aya_profile, first_name="Kouadio",
            defaults=dict(class_level="6ème", target_subjects=["Mathématiques"]),
        )

        bakary, _ = self._get_or_create_user(
            "bakary.parent@xporadia.ci", UserRole.PARENT, "Bakary", "Diallo", "+2250700000012"
        )
        bakary_profile, _ = ParentProfile.objects.get_or_create(
            user=bakary, defaults=dict(location="Yopougon, Abidjan", subscription_active=False)
        )
        mariam_child, _ = Child.objects.get_or_create(
            parent=bakary_profile, first_name="Mariam Jr",
            defaults=dict(class_level="5ème", target_subjects=["Anglais"]),
        )

        # --- Entreprises ---
        serge, _ = self._get_or_create_user(
            "contact.entreprise@xporadia.ci", UserRole.COMPANY, "Serge", "Kouadio", "+2250700000004"
        )
        CompanyProfile.objects.get_or_create(
            user=serge,
            defaults=dict(
                company_name="Ivoire Digital Solutions", sector="Technologies de l'éducation",
                address="Plateau, Abidjan", is_partner=False,
            ),
        )

        nadege, _ = self._get_or_create_user(
            "rh.entreprise2@xporadia.ci", UserRole.COMPANY, "Nadège", "Yao", "+2250700000013"
        )
        CompanyProfile.objects.get_or_create(
            user=nadege,
            defaults=dict(
                company_name="Abidjan Tech Hub", sector="Numérique", address="Marcory, Abidjan",
                is_partner=True,
            ),
        )

        users.update(
            teachers={"awa": awa, "yao": yao, "aminata": aminata, "ibrahim": ibrahim, "mariam": mariam},
            directors={"kouassi": kouassi, "adjoua": adjoua},
            parents={"fatou": fatou, "aya": aya, "bakary": bakary},
            children={"aicha": aicha, "ibrahim_jr": ibrahim_child, "kouadio": kouadio, "mariam_jr": mariam_child},
            companies={"serge": serge, "nadege": nadege},
        )
        return users

    # ------------------------------------------------------------------
    # Catalogue de certification
    # ------------------------------------------------------------------
    def _seed_certification_catalog(self, users):
        trainer, created = self._get_or_create_user(
            "konan.trainer@xporadia.ci", UserRole.TRAINER, "Konan", "Assi", "+2250700000005"
        )

        module_defs = [
            dict(
                title="Fondamentaux pédagogiques", category=ModuleCategory.PEDAGOGY,
                description="Bases de la pédagogie active et de la gestion d'une salle de classe.",
                objectives=["Maîtriser les méthodes actives", "Structurer une séquence pédagogique"],
                duration_hours=8, price=15000, target_level=CertificationLevel.BRONZE,
            ),
            dict(
                title="Éthique professionnelle", category=ModuleCategory.ETHICS,
                description="Déontologie de l'enseignant et relation avec les familles.",
                objectives=["Connaître le cadre déontologique", "Gérer les situations sensibles"],
                duration_hours=6, price=12000, target_level=CertificationLevel.BRONZE,
            ),
            dict(
                title="Didactique disciplinaire", category=ModuleCategory.DIDACTICS,
                description="Approfondissement des méthodes d'enseignement par discipline.",
                objectives=["Adapter sa didactique à la discipline", "Concevoir des évaluations pertinentes"],
                duration_hours=12, price=25000, target_level=CertificationLevel.SILVER,
            ),
            dict(
                title="Gestion de classe avancée", category=ModuleCategory.MANAGEMENT,
                description="Techniques avancées de gestion de groupe et de discipline positive.",
                objectives=["Prévenir les conflits", "Animer une classe hétérogène"],
                duration_hours=10, price=22000, target_level=CertificationLevel.SILVER,
            ),
            dict(
                title="Leadership pédagogique", category=ModuleCategory.LEADERSHIP,
                description="Devenir référent pédagogique au sein de son établissement.",
                objectives=["Encadrer des pairs", "Piloter un projet pédagogique d'établissement"],
                duration_hours=16, price=40000, target_level=CertificationLevel.GOLD,
            ),
        ]
        modules = {}
        for data in module_defs:
            module, created = TrainingModule.objects.get_or_create(title=data["title"], defaults=data)
            modules[module.title] = module
            if created:
                self.stdout.write(self.style.SUCCESS(f"Module créé : {module.title}"))

        # Questions QCM/Vrai-Faux pour l'examen en ligne du module Bronze de base.
        bronze_module = modules["Fondamentaux pédagogiques"]
        exam_questions = [
            dict(question_type=QuestionType.MCQ, text="Quelle méthode favorise l'apprentissage actif ?",
                 options=["Le cours magistral seul", "La pédagogie de projet", "La copie de leçon"],
                 correct_answer="La pédagogie de projet", points=2),
            dict(question_type=QuestionType.MCQ, text="Combien de temps dure en moyenne une séquence pédagogique ?",
                 options=["5 minutes", "45 à 60 minutes", "1 semaine"],
                 correct_answer="45 à 60 minutes", points=1),
            dict(question_type=QuestionType.TF, text="Un enseignant doit varier ses méthodes pédagogiques.",
                 options=[], correct_answer="Vrai", points=1),
            dict(question_type=QuestionType.TF, text="La gestion de classe ne concerne que la discipline.",
                 options=[], correct_answer="Faux", points=1),
        ]
        for q in exam_questions:
            ExamQuestion.objects.get_or_create(module=bronze_module, text=q["text"], defaults=q)

        upcoming_date = TODAY() + datetime.timedelta(days=14)
        for title, module in modules.items():
            TrainingSession.objects.get_or_create(
                module=module, trainer=trainer, date=upcoming_date,
                defaults=dict(
                    city="Abidjan", location="Centre de formation Epsilon, Cocody",
                    start_time="09:00", end_time="17:00", capacity=25, status=SessionStatus.PLANNED,
                ),
            )
        # Une deuxième session, dans une autre ville, pour un module Silver.
        TrainingSession.objects.get_or_create(
            module=modules["Didactique disciplinaire"], trainer=trainer,
            date=TODAY() + datetime.timedelta(days=21),
            defaults=dict(
                city="Bouaké", location="Antenne Epsilon Bouaké",
                start_time="09:00", end_time="16:00", capacity=20, status=SessionStatus.PLANNED,
            ),
        )
        return modules

    def _issue_certification(self, teacher, module, score=85):
        if Certification.objects.filter(teacher=teacher, module=module).exists():
            return
        attempt = ExamAttempt.objects.create(teacher=teacher, score_total=score, status="graded")
        Certification.objects.create(
            teacher=teacher, module=module, attempt=attempt, level=module.target_level,
            score_total=score, qr_code=f"XPO-CERT-{teacher.id}-{module.target_level}-DEMO",
            expires_at=TODAY() + datetime.timedelta(days=CERT_VALIDITY_DAYS),
        )
        self.stdout.write(self.style.SUCCESS(f"Certification {module.target_level} créée pour {teacher.email}"))

    def _seed_certifications(self, users, modules):
        teachers = users["teachers"]
        # Awa : Bronze seul (en cours de progression).
        self._issue_certification(teachers["awa"], modules["Fondamentaux pédagogiques"], score=88)
        # Yao : Bronze + Silver.
        self._issue_certification(teachers["yao"], modules["Fondamentaux pédagogiques"], score=91)
        self._issue_certification(teachers["yao"], modules["Didactique disciplinaire"], score=79)
        # Aminata : Bronze + Silver + Gold (illustre le privilège "demande d'emploi").
        self._issue_certification(teachers["aminata"], modules["Fondamentaux pédagogiques"], score=95)
        self._issue_certification(teachers["aminata"], modules["Gestion de classe avancée"], score=87)
        self._issue_certification(teachers["aminata"], modules["Leadership pédagogique"], score=90)
        # Mariam : Bronze.
        self._issue_certification(teachers["mariam"], modules["Éthique professionnelle"], score=82)
        # Ibrahim : aucune certification pour l'instant (profil "débutant").

    # ------------------------------------------------------------------
    # Structure académique + inscriptions
    # ------------------------------------------------------------------
    def _seed_academics(self, users):
        teachers = users["teachers"]
        directors = users["directors"]
        children = users["children"]
        school_year = "2025-2026"

        # --- Établissement 1 : Groupe Scolaire La Réussite ---
        dept1, _ = Department.objects.get_or_create(
            establishment=directors["kouassi"].director_profile, name="Primaire et Collège"
        )
        track1, _ = Track.objects.get_or_create(department=dept1, name="Générale")
        cm2, _ = SchoolClass.objects.get_or_create(
            track=track1, name="CM2 A", school_year=school_year,
            defaults=dict(homeroom_teacher=teachers["ibrahim"], capacity=35),
        )
        cinquieme, _ = SchoolClass.objects.get_or_create(
            track=track1, name="5ème A", school_year=school_year,
            defaults=dict(homeroom_teacher=teachers["yao"], capacity=40),
        )
        subj_francais, _ = Subject.objects.get_or_create(
            school_class=cm2, name="Français", defaults=dict(teacher=teachers["ibrahim"])
        )
        subj_maths_cm2, _ = Subject.objects.get_or_create(
            school_class=cm2, name="Mathématiques", defaults=dict(teacher=teachers["mariam"])
        )
        subj_anglais, _ = Subject.objects.get_or_create(
            school_class=cinquieme, name="Anglais", defaults=dict(teacher=teachers["yao"])
        )
        subj_svt, _ = Subject.objects.get_or_create(
            school_class=cinquieme, name="SVT", defaults=dict(teacher=teachers["aminata"])
        )

        # --- Établissement 2 : Institution Sainte Marie ---
        dept2, _ = Department.objects.get_or_create(
            establishment=directors["adjoua"].director_profile, name="Collège"
        )
        track2, _ = Track.objects.get_or_create(department=dept2, name="Générale")
        sixieme, _ = SchoolClass.objects.get_or_create(
            track=track2, name="6ème B", school_year=school_year,
            defaults=dict(homeroom_teacher=teachers["aminata"], capacity=38),
        )
        subj_maths_6e, _ = Subject.objects.get_or_create(
            school_class=sixieme, name="Mathématiques", defaults=dict(teacher=teachers["aminata"])
        )

        # --- Inscriptions des enfants ---
        Enrollment.objects.get_or_create(child=children["ibrahim_jr"], school_class=cm2, defaults=dict(status="active"))
        Enrollment.objects.get_or_create(child=children["aicha"], school_class=cinquieme, defaults=dict(status="active"))
        Enrollment.objects.get_or_create(child=children["kouadio"], school_class=sixieme, defaults=dict(status="active"))
        Enrollment.objects.get_or_create(child=children["mariam_jr"], school_class=cinquieme, defaults=dict(status="active"))

        return {
            "kouassi": {"profile": directors["kouassi"].director_profile, "department": dept1, "track": track1,
                        "classes": {"cm2": cm2, "5eme": cinquieme},
                        "subjects": {"francais": subj_francais, "maths_cm2": subj_maths_cm2,
                                     "anglais": subj_anglais, "svt": subj_svt}},
            "adjoua": {"profile": directors["adjoua"].director_profile, "department": dept2, "track": track2,
                       "classes": {"6eme": sixieme}, "subjects": {"maths_6e": subj_maths_6e}},
        }

    # ------------------------------------------------------------------
    # Espace numérique (cours/exercices) + soumissions d'élève
    # ------------------------------------------------------------------
    def _seed_virtual_classes(self, establishments, users):
        subjects = establishments["kouassi"]["subjects"]
        children = users["children"]

        vc_maths, _ = VirtualClass.objects.get_or_create(
            subject=subjects["maths_cm2"], defaults=dict(description="Espace de la classe de CM2 A — mathématiques.")
        )
        ex_fractions, _ = Exercise.objects.get_or_create(
            virtual_class=vc_maths, title="Devoir sur les fractions",
            defaults=dict(
                instructions="Faire les exercices 1 à 5 page 42 sur les fractions.",
                status=ExerciseStatus.PUBLISHED, published_at=timezone.now(),
            ),
        )
        submission, created = Submission.objects.get_or_create(
            exercise=ex_fractions, child=children["ibrahim_jr"],
            defaults=dict(
                submitted_by=children["ibrahim_jr"].parent.user, content="Voici mes réponses aux 5 exercices.",
                status="graded", grade=15.5, feedback="Bon travail, attention aux fractions équivalentes.",
                graded_at=timezone.now(),
            ),
        )

        vc_anglais, _ = VirtualClass.objects.get_or_create(
            subject=subjects["anglais"], defaults=dict(description="Espace de la classe de 5ème A — anglais.")
        )
        ex_vocab, _ = Exercise.objects.get_or_create(
            virtual_class=vc_anglais, title="Vocabulaire — la famille",
            defaults=dict(
                instructions="Apprendre le vocabulaire de la famille et faire l'exercice joint.",
                status=ExerciseStatus.PUBLISHED, published_at=timezone.now(),
            ),
        )
        Submission.objects.get_or_create(
            exercise=ex_vocab, child=children["aicha"],
            defaults=dict(
                submitted_by=children["aicha"].parent.user, content="My family is composed of...",
                status="submitted",
            ),
        )
        # Un devoir encore en brouillon pour illustrer le flux enseignant.
        Exercise.objects.get_or_create(
            virtual_class=vc_anglais, title="Contrôle — temps du passé",
            defaults=dict(instructions="Contrôle sur le prétérit, à publier la semaine prochaine.", status=ExerciseStatus.DRAFT),
        )

    # ------------------------------------------------------------------
    # Bibliothèque numérique
    # ------------------------------------------------------------------
    def _seed_library(self, establishments, users):
        teachers = users["teachers"]
        kouassi_profile = establishments["kouassi"]["profile"]
        LibraryResource.objects.get_or_create(
            establishment=kouassi_profile,
            title="Cours — Les fractions au CM2",
            defaults=dict(
                description="Support de cours complet sur les fractions.", resource_type=ResourceType.COURSE,
                level=SchoolLevel.SIXIEME,
                subject="Mathématiques", file_url="https://example.com/demo/fractions-cm2.pdf",
                file_size_kb=850, tags=["fractions", "cm2"], author=teachers["mariam"],
                moderation_status=ModerationStatus.APPROVED,
            ),
        )
        LibraryResource.objects.get_or_create(
            establishment=kouassi_profile,
            title="Fiche de révision — Vocabulaire de la famille",
            defaults=dict(
                description="Fiche de vocabulaire anglais à réviser avant le contrôle.",
                resource_type=ResourceType.REVISION,
                level=SchoolLevel.CINQUIEME,
                subject="Anglais", file_url="https://example.com/demo/vocab-famille.pdf",
                file_size_kb=210, tags=["vocabulaire", "famille"], author=teachers["yao"],
                moderation_status=ModerationStatus.APPROVED,
            ),
        )

    # ------------------------------------------------------------------
    # Marché de l'emploi
    # ------------------------------------------------------------------
    def _seed_employment(self, users):
        directors = users["directors"]
        teachers = users["teachers"]

        listing_active, _ = JobListing.objects.get_or_create(
            school=directors["kouassi"], title="Enseignant(e) de Mathématiques — Collège",
            defaults=dict(
                subject="Mathématiques", levels=["6ème", "5ème"], contract_type=ContractType.CDI,
                salary_min=150000, salary_max=220000, cert_level_required=CertificationLevel.BRONZE,
                description="Recherche enseignant(e) de mathématiques pour la rentrée, poste à pourvoir immédiatement.",
                city="Abidjan", commune="Cocody", status=JobStatus.ACTIVE, published_at=timezone.now(),
            ),
        )
        application, _ = JobApplication.objects.get_or_create(
            teacher=teachers["ibrahim"], listing=listing_active,
            defaults=dict(cover_letter="Je suis très motivé pour rejoindre votre équipe pédagogique.",
                          status=ApplicationStatus.PENDING),
        )
        notify_user(directors["kouassi"], NotificationType.NEW_JOB_OFFER,
                    title="Nouvelle candidature", body=f"{teachers['ibrahim'].get_full_name()} a postulé à votre offre.",
                    send_push=False)

        # Un recrutement déjà conclu, pour illustrer l'historique.
        recruitment, created = Recruitment.objects.get_or_create(
            school=directors["adjoua"], teacher=teachers["aminata"],
            defaults=dict(salary_agreed=250000),
        )
        if created:
            notify_user(teachers["aminata"], NotificationType.RECRUITMENT,
                        title="Recrutement confirmé", body="Votre recrutement chez Institution Sainte Marie est confirmé.",
                        send_push=False)

        JobListing.objects.get_or_create(
            school=directors["adjoua"], title="Enseignant(e) d'Anglais — Lycée",
            defaults=dict(
                subject="Anglais", levels=["Seconde", "Première"], contract_type=ContractType.CDD,
                cert_level_required=CertificationLevel.BRONZE,
                description="Brouillon d'offre en préparation.", city="Yopougon", status=JobStatus.DRAFT,
            ),
        )

        # Demande d'emploi (privilège Or) pour Aminata, seule enseignante Gold.
        JobSeekingRequest.objects.get_or_create(
            teacher=teachers["aminata"],
            defaults=dict(subjects=["SVT", "Mathématiques"], city="Abidjan",
                          message="Disponible immédiatement pour un poste à temps plein."),
        )

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def _seed_internships(self, users, establishments):
        companies = users["companies"]
        directors = users["directors"]
        children = users["children"]

        offer1, _ = InternshipOffer.objects.get_or_create(
            company=companies["serge"], title="Stage découverte — Développement web",
            defaults=dict(
                domain="Numérique", missions="Initiation au développement web, observation des équipes techniques.",
                level=InternshipLevel.COLLEGE, duration_weeks=2,
                period_start=TODAY() + datetime.timedelta(days=30),
                period_end=TODAY() + datetime.timedelta(days=44),
                places=3, city="Abidjan", skills_wanted=["Curiosité", "Autonomie"],
            ),
        )
        application1, _ = InternshipApplication.objects.get_or_create(
            offer=offer1, school=directors["kouassi"], student=children["ibrahim_jr"],
            defaults=dict(motivation="Élève très motivé par le numérique.", status=InternshipApplicationStatus.ACCEPTED),
        )
        convention, _ = InternshipConvention.objects.get_or_create(
            application=application1,
            defaults=dict(status=ConventionStatus.COMPLETE, signed_by_school_at=timezone.now(),
                          signed_by_company_at=timezone.now()),
        )
        InternshipJournal.objects.get_or_create(
            convention=convention, date=TODAY(),
            defaults=dict(content="Première journée : découverte de l'environnement de travail et des équipes."),
        )
        InternshipEvaluation.objects.get_or_create(
            convention=convention,
            defaults=dict(punctuality=5, initiative=4, integration=5, skills=4, global_rating=4,
                          comment="Stagiaire sérieux et curieux, à recommander."),
        )

        offer2, _ = InternshipOffer.objects.get_or_create(
            company=companies["nadege"], title="Stage découverte — Marketing digital",
            defaults=dict(
                domain="Marketing", missions="Support aux campagnes digitales et réseaux sociaux.",
                level=InternshipLevel.SECONDE, duration_weeks=1,
                period_start=TODAY() + datetime.timedelta(days=60),
                period_end=TODAY() + datetime.timedelta(days=67),
                places=2, city="Abidjan",
            ),
        )
        InternshipApplication.objects.get_or_create(
            offer=offer2, school=directors["kouassi"], student=children["aicha"],
            defaults=dict(motivation="Intéressée par le marketing digital.", status=InternshipApplicationStatus.PENDING),
        )

    # ------------------------------------------------------------------
    # Cours particuliers
    # ------------------------------------------------------------------
    def _seed_tutoring(self, users):
        teachers = users["teachers"]
        parents = users["parents"]

        completed_session, created = TutoringSession.objects.get_or_create(
            teacher=teachers["aminata"], parent=parents["fatou"],
            child_name="Aïcha", child_level="5ème", subject="SVT", mode="home",
            date=TODAY() - datetime.timedelta(days=5),
            defaults=dict(
                start_time="16:00", duration_min=90, address="Marcory, Abidjan",
                gross_amount=8500, status=TutoringSessionStatus.COMPLETED,
                escrow_released=True, released_at=timezone.now(),
                confirmed_at=timezone.now() - datetime.timedelta(days=6),
            ),
        )
        if created:
            payment = _payment(parents["fatou"], 8500, PaymentType.TUTORING, PaymentStatus.COMPLETED, completed_session)
            TutoringReview.objects.get_or_create(
                session=completed_session, author=parents["fatou"],
                defaults=dict(author_type="parent", rating=5, comment="Excellente pédagogue, ma fille progresse vite."),
            )

        confirmed_session, created = TutoringSession.objects.get_or_create(
            teacher=teachers["awa"], parent=parents["aya"],
            child_name="Kouadio", child_level="6ème", subject="Mathématiques", mode="online",
            date=TODAY() + datetime.timedelta(days=4),
            defaults=dict(
                start_time="17:00", duration_min=60, gross_amount=6000,
                status=TutoringSessionStatus.CONFIRMED, confirmed_at=timezone.now(),
            ),
        )
        if created:
            _payment(parents["aya"], 6000, PaymentType.TUTORING, PaymentStatus.ESCROW, confirmed_session)

    # ------------------------------------------------------------------
    # Inscription à une session de formation (paiement direct plateforme)
    # ------------------------------------------------------------------
    def _seed_training_enrollment(self, users, modules):
        ibrahim = users["teachers"]["ibrahim"]
        session = TrainingSession.objects.filter(module=modules["Fondamentaux pédagogiques"]).first()
        if not session:
            return
        enrollment, created = SessionEnrollment.objects.get_or_create(
            session=session, teacher=ibrahim, defaults=dict(payment_status="paid"),
        )
        if created:
            payment = _payment(ibrahim, session.module.price, PaymentType.TRAINING, PaymentStatus.COMPLETED, None)
            enrollment.payment = payment
            enrollment.save(update_fields=["payment"])
            session.enrolled_count += 1
            session.save(update_fields=["enrolled_count"])
