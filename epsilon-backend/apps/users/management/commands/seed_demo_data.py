import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Department, Enrollment, SchoolClass, Subject, TimetableSlot, Track, Weekday
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
from apps.feed.models import Post, PostComment, PostLike
from apps.messaging.models import Channel, ChannelType, Message
from apps.messaging.services import create_subject_channel, ensure_student_messaging
from apps.student_life.models import BucketListItem, LifeGoal, PersonalNote
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
from apps.grading.models import EstablishmentJoinRequest, JoinRequestStatus

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
            self._seed_training_enrollment(users, modules)
            self._seed_feed(users)
            self._seed_student_activation(establishments, users)
            self._seed_bulk_expansion(establishments, users, modules)
            self._seed_self_registration_flow(establishments)
            self._seed_admin_accounts()

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
        MODULE_POINTS_BY_LEVEL = {
            CertificationLevel.BRONZE: 10,
            CertificationLevel.SILVER: 25,
            CertificationLevel.GOLD: 50,
        }
        for data in module_defs:
            data.setdefault("points", MODULE_POINTS_BY_LEVEL[data["target_level"]])
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
            points_awarded=module.points, score_total=score,
            qr_code=f"XPO-CERT-{teacher.id}-{module.target_level}-DEMO",
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

    # ------------------------------------------------------------------
    # Fil d'actualité — publications, j'aime, commentaires
    # ------------------------------------------------------------------
    def _seed_feed(self, users):
        teachers = users["teachers"]
        directors = users["directors"]
        parents = users["parents"]
        companies = users["companies"]

        posts_data = [
            dict(
                author=teachers["awa"],
                body=(
                    "Ravie d'avoir décroché ma certification Argent ce mois-ci ! Merci à l'équipe "
                    "pédagogique Xporadia pour l'accompagnement pendant le module de didactique."
                ),
                days_ago=6,
            ),
            dict(
                author=directors["kouassi"],
                body=(
                    "Le Collège Fraternité recrute deux enseignants de Mathématiques certifiés Or "
                    "pour la rentrée. Les candidatures se font directement via l'annuaire Xporadia."
                ),
                days_ago=4,
            ),
            dict(
                author=teachers["ibrahim"],
                body=(
                    "Petit retour d'expérience après ma première session de cours particuliers via "
                    "la plateforme : l'outil de suivi de progression change vraiment la donne."
                ),
                days_ago=3,
            ),
            dict(
                author=companies["nadege"],
                body=(
                    "Abidjan Tech Hub ouvre 5 nouvelles places de stage pour les élèves de Terminale "
                    "intéressés par le développement web. Missions concrètes, encadrement dédié."
                ),
                days_ago=2,
            ),
            dict(
                author=parents["fatou"],
                body=(
                    "Merci à la communauté enseignante pour vos conseils sur l'accompagnement en SVT — "
                    "les progrès de ma fille depuis la rentrée sont impressionnants."
                ),
                days_ago=1,
            ),
            dict(
                author=teachers["aminata"],
                body="Session de formation continue sur la gestion de classe très enrichissante ce week-end à Cocody.",
                days_ago=0,
            ),
        ]

        likers = [teachers["yao"], teachers["mariam"], parents["aya"], directors["adjoua"], parents["bakary"]]
        comments_bank = [
            "Merci pour ce retour, très utile !",
            "Félicitations, bien mérité.",
            "Je suis intéressé, comment postuler ?",
            "Xporadia continue de prouver sa valeur sur le terrain.",
        ]

        for i, data in enumerate(posts_data):
            post, created = Post.objects.get_or_create(
                author=data["author"], body=data["body"],
                defaults=dict(created_at=timezone.now() - datetime.timedelta(days=data["days_ago"])),
            )
            if not created:
                continue
            # created_at a auto_now_add=True — on le corrige après coup pour
            # étaler les publications dans le temps (fil chronologique crédible).
            Post.objects.filter(pk=post.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=data["days_ago"])
            )
            for liker in likers[: (i % len(likers)) + 2]:
                PostLike.objects.get_or_create(post=post, user=liker)
            for j, comment_author in enumerate([teachers["yao"], parents["aya"]][: i % 3]):
                PostComment.objects.get_or_create(
                    post=post, author=comment_author, body=comments_bank[(i + j) % len(comments_bank)],
                )

        self.stdout.write(self.style.SUCCESS(f"Fil d'actualité : {len(posts_data)} publication(s) de démo créées."))

    # ------------------------------------------------------------------
    # Compte élève de démonstration — activation directe (sans passer par
    # le lien email) pour que le profil Élève soit testable immédiatement,
    # avec emploi du temps, canaux de matière peuplés, et espace personnel
    # (objectif de vie, bucket list, note) déjà renseignés.
    # ------------------------------------------------------------------
    def _seed_student_activation(self, establishments, users):
        children = users["children"]
        aicha = children["aicha"]

        if not aicha.user_id:
            student_user = User.objects.create_user(
                email="aicha.eleve@xporadia.ci",
                password="Xporadia2026!",
                first_name=aicha.first_name,
                last_name="Koné",
                primary_role=UserRole.STUDENT,
                is_verified=True,
                is_documents_validated=True,
            )
            aicha.user = student_user
            aicha.last_name = "Koné"
            aicha.save(update_fields=["user", "last_name"])
        ensure_student_messaging(aicha)

        cinquieme = establishments["kouassi"]["classes"]["5eme"]
        subj_anglais = establishments["kouassi"]["subjects"]["anglais"]
        subj_svt = establishments["kouassi"]["subjects"]["svt"]

        TimetableSlot.objects.get_or_create(
            school_class=cinquieme, subject=subj_anglais, weekday=Weekday.MONDAY,
            defaults=dict(start_time="08:00", end_time="09:00", room="Salle 12"),
        )
        TimetableSlot.objects.get_or_create(
            school_class=cinquieme, subject=subj_svt, weekday=Weekday.MONDAY,
            defaults=dict(start_time="09:00", end_time="10:00", room="Labo SVT"),
        )
        TimetableSlot.objects.get_or_create(
            school_class=cinquieme, subject=subj_anglais, weekday=Weekday.WEDNESDAY,
            defaults=dict(start_time="10:15", end_time="11:15", room="Salle 12"),
        )

        # Canal de matière SVT créé par l'enseignant dédié (action délibérée,
        # pas automatique — voir apps.messaging.services), avec un message
        # d'accueil pour que le fil de démonstration ne soit pas vide.
        svt_channel = Channel.objects.filter(channel_type=ChannelType.SUBJECT, subject=subj_svt).first()
        if not svt_channel:
            svt_channel = create_subject_channel(subj_svt, subj_svt.teacher)
            Message.objects.create(
                channel=svt_channel, author=subj_svt.teacher,
                body="Bienvenue dans le canal de SVT — postez vos questions ici entre deux cours.",
            )

        LifeGoal.objects.get_or_create(
            child=aicha,
            defaults=dict(
                description="Devenir ingénieure en informatique et travailler sur des projets qui aident les écoles africaines.",
                related_subjects=["Mathématiques", "SVT", "Anglais"],
            ),
        )
        BucketListItem.objects.get_or_create(
            child=aicha, title="Terminer ma certification en algorithmique junior",
            defaults=dict(description="Module découverte proposé par Xporadia."),
        )
        BucketListItem.objects.get_or_create(
            child=aicha, title="Lire un livre de développement personnel par mois", defaults=dict(is_done=True),
        )
        PersonalNote.objects.get_or_create(
            child=aicha, subject=subj_anglais, title="Vocabulaire — la famille",
            defaults=dict(content="Mother, father, sibling, cousin, nephew, niece..."),
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Compte élève de démo activé : aicha.eleve@xporadia.ci / Xporadia2026! "
                "(emploi du temps, canal de matière et espace personnel peuplés)."
            )
        )

    # ------------------------------------------------------------------
    # Expansion massive — bien plus de comptes, classes, publications,
    # ressources et candidatures pour que l'app soit dense et crédible en
    # démonstration plutôt que peuplée du strict minimum fonctionnel.
    # Idempotent : ne s'exécute qu'une fois (marqueur ci-dessous).
    # ------------------------------------------------------------------
    def _seed_bulk_expansion(self, establishments, users, modules):
        modules_list = list(modules.values())
        import random

        if User.objects.filter(email="bulk.seed.marker@xporadia.ci").exists():
            self.stdout.write("Expansion massive déjà présente, ignorée (idempotence).")
            return

        rng = random.Random(42)

        FIRST_NAMES_F = [
            "Adjoua", "Akissi", "Affoué", "Aya", "Ama", "Rokia", "Fatoumata", "Mariame",
            "Nafissatou", "Salimata", "Djeneba", "Aïssata", "Kadiatou", "Assetou", "Bintou",
            "Awa", "Coumba", "Ramatoulaye", "Khady", "Ndèye",
        ]
        FIRST_NAMES_M = [
            "Yao", "Kouassi", "Koffi", "Konan", "Kouame", "Adama", "Moussa", "Ibrahim",
            "Souleymane", "Mamadou", "Sekou", "Boubacar", "Cheikh", "Abdoulaye", "Lassina",
            "Drissa", "Issouf", "Bakary", "Sidiki", "Vamara",
        ]
        LAST_NAMES = [
            "Kouassi", "Kone", "Traore", "Coulibaly", "Diabate", "Ouattara", "Bamba", "Diarra",
            "Toure", "Camara", "Sanogo", "Kante", "Sangare", "Fofana", "Diallo", "Cisse",
            "Yeo", "Silue", "Soro", "N'Guessan", "Kouame", "Assi", "Brou", "Angoua", "Kacou",
        ]
        CITIES = ["Abidjan", "Bouaké", "Yamoussoukro", "San-Pédro", "Korhogo", "Daloa", "Man", "Gagnoa"]
        SUBJECTS_BANK = [
            "Mathématiques", "Physique-Chimie", "SVT", "Français", "Anglais", "Histoire-Géographie",
            "Philosophie", "EPS", "Arts Plastiques", "Espagnol", "Allemand", "Économie",
        ]
        SCHOOL_LEVELS = ["6e", "5e", "4e", "3e", "2nde", "1ere", "tle"]
        POST_TOPICS = [
            ("Ravi(e) d'avoir terminé le module {module} cette semaine, la formation était dense mais "
             "vraiment utile pour ma pratique en classe. #{hashtag1} #formation"),
            ("Nouvelle promotion d'élèves accueillie ce matin à {city}. Une rentrée pleine d'énergie "
             "! #{hashtag1} #rentree"),
            ("Question à la communauté : quelles ressources conseillez-vous pour préparer le BEPC en "
             "{subject} ? #{hashtag1} #entraide"),
            ("Session de cours particuliers très enrichissante hier soir avec un élève de {level}. "
             "Les progrès en quelques semaines sont impressionnants. #{hashtag1} #tutorat"),
            ("Notre établissement recrute des enseignants certifiés en {subject} pour {city}. "
             "Candidatures ouvertes via l'annuaire Xporadia. #{hashtag1} #recrutement"),
            ("Petit rappel pour les élèves : la bibliothèque numérique s'est enrichie de nouvelles "
             "fiches de révision en {subject} cette semaine. #{hashtag1} #bibliotheque"),
            ("Fier de mes élèves qui ont particulièrement bien réussi le dernier contrôle de "
             "{subject}. Le travail paie ! #{hashtag1} #reussite"),
            ("Stage de découverte très riche pour nos élèves de {level} chez nos entreprises "
             "partenaires cette semaine. #{hashtag1} #stage"),
        ]
        HASHTAGS_BANK = [
            "education", "xporadia", "pedagogie", "cotedivoire", "enseignement", "college", "lycee",
            "certification", "abidjan", "afrique",
        ]
        COMMENTS_BANK = [
            "Merci pour ce partage !", "Bravo, bien mérité.", "Très intéressant, merci.",
            "Je suis intéressé, comment en savoir plus ?", "Xporadia continue de faire la différence.",
            "Excellente initiative.", "Bon courage pour la suite !",
        ]

        # --- 1. Enseignants supplémentaires (25) ---
        new_teachers = []
        for i in range(25):
            is_f = rng.random() < 0.5
            first = rng.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M)
            last = rng.choice(LAST_NAMES)
            email = f"teacher{i}.{first.lower()}@xporadia.ci"
            if User.objects.filter(email=email).exists():
                continue
            user = User.objects.create_user(
                email=email, password=DEMO_PASSWORD, first_name=first, last_name=last,
                primary_role=UserRole.TEACHER, is_verified=True, is_documents_validated=True,
            )
            TeacherProfile.objects.get_or_create(
                user=user,
                defaults=dict(
                    subjects=[rng.choice(SUBJECTS_BANK) for _ in range(rng.randint(1, 2))],
                    bio="Enseignant(e) engagé(e) dans la réussite de ses élèves.",
                    hourly_rate=rng.choice([2500, 3000, 3500, 4000]),
                    location=rng.choice(CITIES),
                    experience_years=rng.randint(1, 15),
                ),
            )
            if modules_list:
                self._issue_certification(user, rng.choice(modules_list), score=rng.randint(65, 98))
            new_teachers.append(user)

        # --- 2. Classes et matières supplémentaires dans les 2 établissements existants ---
        new_subjects = []
        new_classes = []
        for key in ("kouassi", "adjoua"):
            dept = establishments[key]["department"]
            track = establishments[key]["track"]
            for level in rng.sample(SCHOOL_LEVELS, 3):
                class_name = f"{level.upper()} {rng.choice('ABC')}"
                sc, created = SchoolClass.objects.get_or_create(
                    track=track, name=class_name, school_year="2025-2026",
                    defaults=dict(
                        homeroom_teacher=rng.choice(new_teachers) if new_teachers else None, capacity=40,
                    ),
                )
                if created:
                    new_classes.append(sc)
                for subject_name in rng.sample(SUBJECTS_BANK, 4):
                    subj, s_created = Subject.objects.get_or_create(
                        school_class=sc, name=subject_name,
                        defaults=dict(teacher=rng.choice(new_teachers) if new_teachers else None),
                    )
                    if s_created:
                        new_subjects.append(subj)
                # Emploi du temps sommaire pour chaque nouvelle classe.
                if created:
                    for day in range(5):
                        subject_of_day = rng.choice(sc.subjects.all()) if sc.subjects.exists() else None
                        if subject_of_day:
                            hour = 8 + day
                            TimetableSlot.objects.get_or_create(
                                school_class=sc, subject=subject_of_day, weekday=day,
                                defaults=dict(
                                    start_time=f"{hour:02d}:00", end_time=f"{hour + 1:02d}:00",
                                    room=f"Salle {rng.randint(1, 20)}",
                                ),
                            )

        # --- 3. Parents et enfants supplémentaires, une partie activés élèves ---
        new_children = []
        for i in range(40):
            is_f = rng.random() < 0.5
            first = rng.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M)
            last = rng.choice(LAST_NAMES)
            parent_email = f"parent{i}.{first.lower()}@xporadia.ci"
            if User.objects.filter(email=parent_email).exists():
                continue
            parent_user = User.objects.create_user(
                email=parent_email, password=DEMO_PASSWORD, first_name=first, last_name=last,
                primary_role=UserRole.PARENT, is_verified=True, is_documents_validated=True,
            )
            parent_profile, _ = ParentProfile.objects.get_or_create(user=parent_user)
            child_first = rng.choice(FIRST_NAMES_F if rng.random() < 0.5 else FIRST_NAMES_M)
            child = Child.objects.create(
                parent=parent_profile, first_name=child_first, last_name=last,
                class_level=rng.choice(SCHOOL_LEVELS).upper(),
            )
            target_class = rng.choice(new_classes) if new_classes else None
            if target_class:
                Enrollment.objects.get_or_create(child=child, school_class=target_class, defaults=dict(status="active"))
            # Un enfant sur trois environ obtient un compte élève activé.
            if rng.random() < 0.35:
                student_user = User.objects.create_user(
                    email=f"student{i}.{child_first.lower()}@xporadia.ci", password=DEMO_PASSWORD,
                    first_name=child_first, last_name=last, primary_role=UserRole.STUDENT,
                    is_verified=True, is_documents_validated=True,
                )
                child.user = student_user
                child.save(update_fields=["user"])
                ensure_student_messaging(child)
            new_children.append(child)

        all_authors = (
            list(users["teachers"].values())
            + list(users["directors"].values())
            + new_teachers
            + [c.user for c in new_children if c.user_id]
        )

        # --- 4. Abonnements aléatoires (réseau) ---
        from apps.feed.models import Follow

        follow_pairs = set()
        for _ in range(120):
            if len(all_authors) < 2:
                break
            a, b = rng.sample(all_authors, 2)
            follow_pairs.add((a.id, b.id))
        Follow.objects.bulk_create(
            [Follow(follower_id=a, followed_id=b) for a, b in follow_pairs], ignore_conflicts=True
        )

        # --- 5. Publications supplémentaires (60), avec likes et commentaires ---
        for i in range(60):
            if not all_authors:
                break
            author = rng.choice(all_authors)
            template = rng.choice(POST_TOPICS)
            body = template.format(
                module=rng.choice(modules_list).title if modules_list else "Fondamentaux pédagogiques",
                city=rng.choice(CITIES),
                subject=rng.choice(SUBJECTS_BANK),
                level=rng.choice(SCHOOL_LEVELS).upper(),
                hashtag1=rng.choice(HASHTAGS_BANK),
            )
            post = Post.objects.create(author=author, body=body)
            Post.objects.filter(pk=post.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=rng.randint(0, 25), hours=rng.randint(0, 23))
            )
            for liker in rng.sample(all_authors, min(rng.randint(0, 8), len(all_authors))):
                if liker.id != author.id:
                    PostLike.objects.get_or_create(post=post, user=liker)
            for _ in range(rng.randint(0, 3)):
                commenter = rng.choice(all_authors)
                if commenter.id != author.id:
                    PostComment.objects.get_or_create(
                        post=post, author=commenter, body=rng.choice(COMMENTS_BANK)
                    )

        # --- 6. Bibliothèque enrichie (35 ressources) ---
        LIB_TITLES = [
            "Fiche de révision", "Cours complet", "Annale corrigée", "Exercices d'application",
            "Support de cours", "Corrigé type", "Préparation d'examen",
        ]
        for i in range(35):
            establishment = rng.choice(
                [establishments["kouassi"]["profile"], establishments["adjoua"]["profile"]]
            )
            author = rng.choice(new_teachers) if new_teachers else None
            subject_name = rng.choice(SUBJECTS_BANK)
            LibraryResource.objects.get_or_create(
                establishment=establishment,
                title=f"{rng.choice(LIB_TITLES)} — {subject_name} {rng.choice(SCHOOL_LEVELS).upper()} #{i}",
                defaults=dict(
                    resource_type=rng.choice(list(ResourceType)),
                    level=rng.choice(list(SchoolLevel)),
                    subject=subject_name,
                    file_url=f"https://example.com/library/resource-{i}.pdf",
                    author=author,
                    is_contributed=bool(author),
                    moderation_status=ModerationStatus.APPROVED,
                ),
            )

        # --- 7. Offres d'emploi et de stage supplémentaires ---
        companies = list(CompanyProfile.objects.all())
        directors = list(users["directors"].values())
        for i in range(15):
            director = rng.choice(directors)
            JobListing.objects.get_or_create(
                school=director, title=f"Poste enseignant {rng.choice(SUBJECTS_BANK)} #{i}",
                defaults=dict(
                    subject=rng.choice(SUBJECTS_BANK), levels=[rng.choice(SCHOOL_LEVELS)],
                    contract_type=rng.choice(list(ContractType)),
                    salary_min=rng.randint(150000, 250000), salary_max=rng.randint(250000, 400000),
                    description="Poste à pourvoir dès que possible.", status=JobStatus.ACTIVE,
                ),
            )
        for i in range(12):
            if not companies:
                break
            company_profile = rng.choice(companies)
            InternshipOffer.objects.get_or_create(
                company=company_profile.user, title=f"Stage découverte {rng.choice(SUBJECTS_BANK)} #{i}",
                defaults=dict(
                    domain=rng.choice(["Numérique", "Commerce", "Industrie", "Communication"]),
                    missions="Observation et participation aux activités de l'équipe.",
                    level=rng.choice(["3e", "2nde", "1ere", "terminale"]),
                    duration_weeks=rng.randint(1, 4),
                    period_start=TODAY() + datetime.timedelta(days=rng.randint(10, 60)),
                    period_end=TODAY() + datetime.timedelta(days=rng.randint(70, 100)),
                    city=rng.choice(CITIES), places=rng.randint(1, 3),
                ),
            )

        # --- Marqueur d'idempotence ---
        User.objects.create_user(
            email="bulk.seed.marker@xporadia.ci", password=DEMO_PASSWORD,
            first_name="Marqueur", last_name="Seed", primary_role=UserRole.ADMIN,
            is_verified=True, is_active=False,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Expansion massive : {len(new_teachers)} enseignants, {len(new_children)} enfants, "
                f"{len(new_classes)} classes, {len(new_subjects)} matières, 60 publications, "
                "35 ressources bibliothèque, 15 offres d'emploi, 12 offres de stage, "
                f"{len(follow_pairs)} abonnements."
            )
        )

    # ------------------------------------------------------------------
    # Auto-inscription élève — flow complet sans invitation d'un
    # directeur : compte créé directement par l'élève, puis demande de
    # rattachement à un établissement (en attente / approuvée mais pas
    # encore placée / rejetée / cas "Autre" établissement absent de
    # Xporadia). Idempotent via l'email de chaque compte de démo.
    # ------------------------------------------------------------------
    def _seed_self_registration_flow(self, establishments):
        kouassi_profile = establishments["kouassi"]["profile"]

        def _self_registered_student(email, first_name, last_name, declared_level):
            if User.objects.filter(email=email).exists():
                return User.objects.get(email=email), User.objects.get(email=email).child_profile
            user = User.objects.create_user(
                email=email, password=DEMO_PASSWORD, first_name=first_name, last_name=last_name,
                primary_role=UserRole.STUDENT, is_verified=True, is_documents_validated=True,
            )
            child = Child.objects.create(
                parent=None, user=user, first_name=first_name, last_name=last_name,
                class_level=declared_level,
            )
            return user, child

        # 1. Demande en attente — l'élève vient de s'inscrire, le
        # directeur n'a pas encore statué.
        _, child_pending = _self_registered_student(
            "amara.pending@xporadia.ci", "Amara", "Ouattara", "5e"
        )
        EstablishmentJoinRequest.objects.get_or_create(
            child=child_pending,
            defaults=dict(
                establishment=kouassi_profile, declared_level="5e",
                status=JoinRequestStatus.PENDING,
            ),
        )

        # 2. Demande approuvée, mais l'élève n'est ENCORE inscrit dans
        # aucune classe — teste directement l'écran "élèves à placer".
        _, child_approved = _self_registered_student(
            "salimata.approved@xporadia.ci", "Salimata", "Bamba", "4e"
        )
        EstablishmentJoinRequest.objects.get_or_create(
            child=child_approved,
            defaults=dict(
                establishment=kouassi_profile, declared_level="4e",
                status=JoinRequestStatus.APPROVED, reviewed_at=timezone.now(),
            ),
        )

        # 3. Demande rejetée — teste l'affichage du motif et la
        # possibilité de retenter ailleurs.
        _, child_rejected = _self_registered_student(
            "ibrahim.rejected@xporadia.ci", "Ibrahim", "Sanogo", "Terminale"
        )
        EstablishmentJoinRequest.objects.get_or_create(
            child=child_rejected,
            defaults=dict(
                establishment=kouassi_profile, declared_level="Terminale",
                status=JoinRequestStatus.REJECTED, rejection_reason="Effectif de Terminale déjà complet.",
                reviewed_at=timezone.now(),
            ),
        )

        # 4. Cas "Autre" — établissement pas encore sur Xporadia, reste
        # en attente indéfiniment jusqu'à ce qu'il nous rejoigne.
        _, child_other = _self_registered_student(
            "kadiatou.other@xporadia.ci", "Kadiatou", "Diarra", "3e"
        )
        EstablishmentJoinRequest.objects.get_or_create(
            child=child_other,
            defaults=dict(
                establishment=None, other_establishment_name="Collège Moderne d'Adjamé",
                declared_level="3e", status=JoinRequestStatus.PENDING,
            ),
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Flux d'auto-inscription : 4 élèves de démo (en attente / approuvé non placé / "
                "rejeté / cas \"Autre\") — mot de passe commun Xporadia2026!"
            )
        )

    # ------------------------------------------------------------------
    # Comptes administrateurs de démo — 2 admins complets (accès total,
    # is_superuser=True, contournent volontairement les permissions
    # Django) + 1 formateur (is_superuser=False, accès Django Admin
    # réellement restreint via un groupe aux seuls modèles de formation).
    # Aucun de ces comptes ne peut être créé par inscription publique —
    # voir apps.users.views.CreateAdminView, seul chemin après le tout
    # premier bootstrap (manage.py createsuperuser).
    # ------------------------------------------------------------------
    def _seed_admin_accounts(self):
        from django.contrib.auth.models import Group, Permission

        for email, first, last in [
            ("admin1@xporadia.ci", "Awa", "Koffi"),
            ("admin2@xporadia.ci", "Moussa", "Diabaté"),
        ]:
            if not User.objects.filter(email=email).exists():
                User.objects.create_superuser(
                    email=email, password=DEMO_PASSWORD, first_name=first, last_name=last,
                )

        # Groupe "Formateurs" — permissions Django réellement limitées aux
        # modèles de formation, jamais tout le reste de la plateforme.
        formateurs_group, _ = Group.objects.get_or_create(name="Formateurs")
        training_models = ["trainingmodule", "trainingsession", "examquestion", "sessionenrollment"]
        formateurs_group.permissions.set(
            Permission.objects.filter(
                content_type__app_label="certification", content_type__model__in=training_models,
            )
        )

        formateur_email = "formateur@xporadia.ci"
        if not User.objects.filter(email=formateur_email).exists():
            formateur = User.objects.create_user(
                email=formateur_email, password=DEMO_PASSWORD, first_name="Solange", last_name="Yao",
                primary_role=UserRole.ADMIN, is_staff=True, is_superuser=False,
                is_verified=True, is_documents_validated=True,
            )
            formateur.groups.add(formateurs_group)

        self.stdout.write(
            self.style.SUCCESS(
                "Comptes admin de démo : admin1@xporadia.ci, admin2@xporadia.ci (accès total), "
                "formateur@xporadia.ci (accès Django Admin limité à la formation) — "
                f"mot de passe commun {DEMO_PASSWORD}"
            )
        )
