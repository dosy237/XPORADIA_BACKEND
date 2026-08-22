"""
Xporadia — seed_student_showcase

Jeu de données de démonstration vitrine — élève, enseignant titulaire et
parent — bâti comme UN seul écosystème interconnecté (même établissement,
même classe, mêmes personnes) plutôt que des comptes isolés, pour que
chaque rôle voie de vraies données cohérentes en se connectant.

Élève (Kevin Ouattara) : classe avec plusieurs matières et enseignants,
historique de plusieurs trimestres avec des notes sur des échelles
différentes, devoirs dans les trois états (en cours, soumis, corrigé),
messagerie (DM avec un enseignant, DM avec un camarade), bibliothèque
variée, bulletins publiés, agenda (emploi du temps + créneaux personnels
+ un événement d'établissement), et le module Vie & objectifs.

Enseignant (Fatou Diabaté, titulaire ET professeure de Philosophie) :
gestion de classe (bulletins, événements, promotion de fin d'année,
délégation d'emploi du temps), correction de copies, certification
(niveau déjà obtenu + module suivant disponible pour un examen en ligne
réel), formation continue (session à venir avec inscription payée),
emploi (candidature en attente + recrutement déjà confirmé chez un
second établissement), portefeuille (paiements réels).

Parent (Ramata Ouattara) : deux enfants dans des états différents (Kevin,
pleinement suivi ; une seconde enfant ajoutée manuellement, sans compte
propre) + un historique de demande de rattachement déjà résolue, plus un
troisième enfant totalement libre (auto-inscrit, non réclamé par
personne) pour tester en conditions réelles une TOUTE nouvelle demande de
rattachement.

Entièrement idempotent (get_or_create / update_or_create partout, jamais
de création inconditionnelle) : relancer cette commande ne duplique
jamais rien, elle complète seulement ce qui manque. Construit dans son
propre établissement dédié pour ne jamais interférer avec seed_demo_data
ni avec les comptes de test créés manuellement pendant le développement.
"""
import io
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    DelegatedTask,
    Department,
    Enrollment,
    EnrollmentStatus,
    EstablishmentEvent,
    EventAudience,
    EventType,
    PersonalScheduleBlock,
    PersonalScheduleException,
    SchoolClass,
    Subject,
    TaskDelegation,
    TimetableSlot,
    Track,
)
from apps.academics.views import _notify_holiday_declared
from apps.certification.models import (
    AttemptStatus,
    Certification,
    CertificationLevel,
    DifficultyLevel,
    ExamAttempt,
    ExamQuestion,
    ModuleCategory,
    QuestionType,
    SessionEnrollment,
    TrainingModule,
    TrainingSession,
)
from apps.certification.models import SessionStatus as CertSessionStatus
from apps.employment.models import (
    ContractType,
    JobApplication,
    JobListing,
    JobStatus,
    PayrollEntry,
    Recruitment,
    WalletTransaction,
    WorkedHours,
    WorkedHoursStatus,
)
from apps.employment.models import PaymentStatus as RecruitmentPaymentStatus
from apps.feed.models import Follow, Post
from apps.grading.models import Evaluation, EvaluationType, Grade, ReportCard, SubjectReportEntry, Term
from apps.grading.services import compute_class_rankings, compute_general_average, compute_subject_average
from apps.library.models import LibraryResource, ModerationStatus, ResourceCategory, ResourceType, SchoolLevel
from apps.messaging.models import Channel, ChannelType, Message
from apps.messaging.services import (
    create_subject_channel,
    ensure_teacher_dm_channels,
    get_or_create_class_channel,
    get_or_create_direct_channel,
)
from apps.notifications.models import Notification, NotificationType
from apps.payments.models import MobileOperator, Payment, PaymentType
from apps.payments.models import PaymentStatus as PayStatus
from apps.student_life.models import BucketListItem, LifeGoal
from apps.users.models import (
    Child,
    ChildClaimRequest,
    ChildClaimRequestStatus,
    DirectorProfile,
    ParentProfile,
    TeacherProfile,
    User,
    UserRole,
)
from apps.virtual_classes.models import Exercise, ExerciseKind, ExerciseStatus, Submission, SubmissionStatus, VirtualClass

DEMO_PASSWORD = "Xporadia2026!"


def get_or_create_user(email, **fields):
    # get_or_create() n'appelle jamais UserManager.create_user() — les
    # is_verified=True / is_documents_validated=True qu'il applique par
    # défaut (voir UserManager.create_user, extra_fields.setdefault) sont
    # donc perdus ici. Sans ce forçage explicite, un enseignant ou
    # directeur seedé en ORM resterait bloqué derrière l'écran de
    # vérification OTP ET derrière la bannière "Accréditation en attente"
    # (masque l'annuaire, les cours particuliers et le marché de l'emploi)
    # — un compte de démonstration doit être immédiatement utilisable,
    # à égalité avec un compte réellement inscrit et déjà validé.
    defaults = {"password": "!", "is_verified": True, "is_documents_validated": True, **fields}
    user, created = User.objects.get_or_create(email=email, defaults=defaults)
    if created:
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
    else:
        update_fields = []
        if not user.is_verified:
            user.is_verified = True
            update_fields.append("is_verified")
        if not user.is_documents_validated:
            user.is_documents_validated = True
            update_fields.append("is_documents_validated")
        if update_fields:
            user.save(update_fields=update_fields)
    return user, created


def make_demo_pdf_bytes(title: str) -> bytes:
    """PDF minimal mais réellement valide (une page blanche, un titre en
    métadonnées) — un pdf_file de démonstration doit être un vrai fichier
    ouvrable, pas un fichier vide ou du texte brut renommé .pdf."""
    safe_title = title.replace("(", "").replace(")", "").replace("\\", "")
    content = (
        f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        f"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        f"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
        f"4 0 obj<</Title({safe_title})>>endobj\n"
        f"trailer<</Root 1 0 R/Info 4 0 R>>\n%%EOF"
    )
    return content.encode("latin-1", errors="replace")


def make_demo_cover_bytes(size=(300, 400), color=(200, 130, 60)) -> bytes:
    """Petite image JPEG réelle (générée avec Pillow, déjà une dépendance
    de Django pour la validation d'ImageField) — couverture de ressource
    par défaut, mais réutilisée telle quelle pour les avatars de démo
    (carrée, couleur distincte par personne)."""
    from PIL import Image

    img = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


def ensure_avatar(user, color):
    """Backfill idempotent d'une vraie photo de profil (pas juste des
    initiales) — sans ceci, aucun compte de démonstration n'a jamais de
    vrai avatar en base, rendant impossible toute vérification réelle du
    rendu \"vraie photo vs. initiales\" sur les écrans qui l'affichent."""
    if user.avatar:
        return False
    content = make_demo_cover_bytes(size=(240, 240), color=color)
    user.avatar.save(f"avatar_{user.id}.jpg", ContentFile(content), save=True)
    return True


def save_demo_attachment(name: str, content: bytes, content_type: str, upload_to="message_attachments") -> dict:
    """Enregistre un vrai fichier sur le stockage par défaut et renvoie le
    dict {name, url, type} attendu par les champs `attachments` (Message,
    Submission) — même format que save_uploaded_attachments, mais sans
    requête HTTP disponible ici (commande de seed) : l'URL absolue est
    construite directement, cohérente avec les autres médias de démo
    (couvertures/PDF bibliothèque)."""
    from django.core.files.storage import default_storage

    path = default_storage.save(f"{upload_to}/{name}", ContentFile(content))
    return {"name": name, "url": f"http://127.0.0.1:8000{default_storage.url(path)}", "type": content_type}


class Command(BaseCommand):
    help = "Jeu de démonstration complet et idempotent : élève, enseignant titulaire et parent vitrines."

    def handle(self, *args, **options):
        created_counts = {"created": 0, "existing": 0}

        def note(created):
            created_counts["created" if created else "existing"] += 1

        with transaction.atomic():
            # === Établissement + structure ===
            director_user, c = get_or_create_user(
                "demo.directeur.showcase@xporadia.ci", primary_role=UserRole.DIRECTOR,
                first_name="Solange", last_name="Bakayoko",
            )
            note(c)
            director, c = DirectorProfile.objects.get_or_create(
                user=director_user,
                defaults={"school_name": "Lycée Démo Complet", "address": "Cocody, Abidjan", "is_partner": True},
            )
            note(c)

            dept, c = Department.objects.get_or_create(establishment=director, name="Second cycle")
            note(c)
            track, c = Track.objects.get_or_create(department=dept, name="Série D")
            note(c)

            homeroom_user, c = get_or_create_user(
                "demo.titulaire.showcase@xporadia.ci", primary_role=UserRole.TEACHER,
                first_name="Fatou", last_name="Diabaté",
            )
            note(c)

            school_class, c = SchoolClass.objects.get_or_create(
                track=track, name="Terminale D2", school_year="2025-2026",
                defaults={"homeroom_teacher": homeroom_user},
            )
            if not c and school_class.homeroom_teacher_id != homeroom_user.id:
                school_class.homeroom_teacher = homeroom_user
                school_class.save(update_fields=["homeroom_teacher"])
            note(c)

            # === Matières + enseignants dédiés ===
            subject_specs = [
                ("Mathématiques", 4, "demo.prof.maths.showcase@xporadia.ci", "Adama", "Koné"),
                ("Physique-Chimie", 3, "demo.prof.pc.showcase@xporadia.ci", "Nadège", "Yao"),
                ("Français", 3, "demo.prof.francais.showcase@xporadia.ci", "Ibrahim", "Traoré"),
                ("Anglais", 2, "demo.prof.anglais.showcase@xporadia.ci", "Christelle", "Aka"),
            ]
            subjects = {}
            for name, coeff, email, first, last in subject_specs:
                teacher, c1 = get_or_create_user(email, primary_role=UserRole.TEACHER, first_name=first, last_name=last)
                note(c1)
                if name == "Mathématiques":
                    note(ensure_avatar(teacher, (58, 92, 148)))
                # TeacherProfile n'est créé par aucun signal — seulement par
                # RegisterTeacherSerializer à l'inscription réelle. Sans ce
                # get_or_create explicite ici, un enseignant seedé en ORM
                # n'en a jamais un, ce qui viderait sa propre fiche profil.
                TeacherProfile.objects.get_or_create(
                    user=teacher, defaults={"subjects": [name], "experience_years": 5, "hourly_rate": Decimal("6000")},
                )
                subject, c2 = Subject.objects.get_or_create(
                    school_class=school_class, name=name, defaults={"coefficient": coeff, "teacher": teacher},
                )
                if not c2 and subject.teacher_id != teacher.id:
                    subject.teacher = teacher
                    subject.coefficient = coeff
                    subject.save(update_fields=["teacher", "coefficient"])
                note(c2)
                VirtualClass.objects.get_or_create(subject=subject)
                subjects[name] = subject

            # === Enseignante titulaire = aussi professeure d'une matière ===
            # Fatou (titulaire) n'enseignait jusqu'ici aucune matière : pour
            # tester ses fonctionnalités (grille de notes, canal de matière,
            # copies à corriger) sans lui voler une matière déjà attribuée à
            # un des 4 enseignants dédiés ci-dessus, elle prend Philosophie.
            homeroom_teacher_profile, c = TeacherProfile.objects.get_or_create(
                user=homeroom_user,
                defaults={
                    "subjects": ["Philosophie"], "experience_years": 11,
                    "hourly_rate": Decimal("7500"), "location": "Cocody, Abidjan",
                    "bio": "Professeure de philosophie et titulaire de Terminale D2, disponible pour "
                           "de l'accompagnement personnalisé et ouverte à de nouvelles opportunités.",
                    "available_for_tutoring": True, "available_for_employment": True,
                },
            )
            note(c)
            note(ensure_avatar(homeroom_user, (150, 90, 130)))
            philo_subject, c = Subject.objects.get_or_create(
                school_class=school_class, name="Philosophie",
                defaults={"coefficient": 2, "teacher": homeroom_user},
            )
            note(c)
            VirtualClass.objects.get_or_create(subject=philo_subject)
            subjects["Philosophie"] = philo_subject

            # === Élève + parent ===
            parent_user, c = get_or_create_user(
                "demo.parent.showcase@xporadia.ci", primary_role=UserRole.PARENT,
                first_name="Ramata", last_name="Ouattara",
            )
            note(c)
            parent, c = ParentProfile.objects.get_or_create(user=parent_user, defaults={"subscription_active": True})
            note(c)

            student_user, c = get_or_create_user(
                "demo.eleve.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Kevin", last_name="Ouattara",
            )
            note(c)
            note(ensure_avatar(student_user, (214, 122, 44)))
            child, c = Child.objects.get_or_create(
                user=student_user,
                defaults={
                    "parent": parent, "first_name": "Kevin", "last_name": "Ouattara",
                    "class_level": "Terminale D", "target_subjects": ["Mathématiques", "Physique-Chimie"],
                    "birth_date": date(2008, 3, 14),
                },
            )
            if not c and child.parent_id != parent.id:
                child.parent = parent
                child.save(update_fields=["parent"])
            note(c)

            enrollment, c = Enrollment.objects.get_or_create(
                child=child, school_class=school_class, defaults={"status": EnrollmentStatus.ACTIVE}
            )
            note(c)

            # Une seconde enfant de Ramata, ajoutée manuellement depuis
            # parent/profile.tsx (pas de compte élève propre, pas encore
            # scolarisée dans une classe suivie par la plateforme) — état
            # distinct de Kevin, pour tester le tableau de bord parent à
            # plusieurs enfants avec un profil sciemment plus vide.
            second_child, c = Child.objects.get_or_create(
                parent=parent, first_name="Aminata", last_name="Ouattara",
                defaults={"class_level": "6ème", "birth_date": date(2014, 9, 2)},
            )
            note(c)

            # Un troisième enfant, auto-inscrit et JAMAIS réclamé par
            # personne (aucune ChildClaimRequest, même pas en attente) —
            # pour tester en conditions réelles une TOUTE nouvelle demande
            # de rattachement depuis parent/claim-child.tsx (recherche par
            # email + soumission), distinct du cas déjà en attente plus bas.
            unclaimed_user, c = get_or_create_user(
                "demo.eleve.libre.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Nafissatou", last_name="Diallo",
            )
            note(c)
            Child.objects.get_or_create(
                user=unclaimed_user,
                defaults={"parent": None, "first_name": "Nafissatou", "last_name": "Diallo", "class_level": "Terminale D"},
            )

            # Un quatrième enfant, réclamé et déjà APPROUVÉ par le passé —
            # pour que l'historique de Ramata (fetchMyChildClaimRequests)
            # affiche aussi une demande résolue, pas seulement l'écran de
            # recherche vide d'une toute première demande.
            approved_child_user, c = get_or_create_user(
                "demo.eleve.neveu.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Yssouf", last_name="Ouattara",
            )
            note(c)
            approved_child, c = Child.objects.get_or_create(
                user=approved_child_user,
                defaults={"parent": parent, "first_name": "Yssouf", "last_name": "Ouattara", "class_level": "Terminale D"},
            )
            note(c)
            _, c = ChildClaimRequest.objects.get_or_create(
                parent=parent, child=approved_child, defaults={"status": ChildClaimRequestStatus.APPROVED},
            )
            note(c)

            # Un camarade de classe pour la messagerie entre élèves.
            classmate_user, c = get_or_create_user(
                "demo.camarade.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Aïcha", last_name="Bamba",
            )
            note(c)
            note(ensure_avatar(classmate_user, (90, 150, 110)))
            classmate, c = Child.objects.get_or_create(
                user=classmate_user,
                defaults={"first_name": "Aïcha", "last_name": "Bamba", "class_level": "Terminale D"},
            )
            note(c)
            Enrollment.objects.get_or_create(
                child=classmate, school_class=school_class, defaults={"status": EnrollmentStatus.ACTIVE}
            )

            # Un second camarade, avec AUCUNE conversation existante — pour
            # tester le démarrage réel d'une toute nouvelle DM depuis Ma
            # classe, distinct du cas où la conversation existe déjà.
            classmate2_user, c = get_or_create_user(
                "demo.camarade2.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Moussa", last_name="Kouadio",
            )
            note(c)
            classmate2, c = Child.objects.get_or_create(
                user=classmate2_user,
                defaults={"first_name": "Moussa", "last_name": "Kouadio", "class_level": "Terminale D"},
            )
            note(c)
            Enrollment.objects.get_or_create(
                child=classmate2, school_class=school_class, defaults={"status": EnrollmentStatus.ACTIVE}
            )

            # === Élève auto-inscrit, pas encore réclamé par un parent ===
            # Child.parent reste nul tant que l'élève n'a pas approuvé une
            # ChildClaimRequest (voir RegisterStudentSerializer côté
            # inscription, ReviewChildClaimRequestView côté approbation) —
            # état distinct du cas Kevin/Ramata où le lien est déjà établi.
            selfreg_user, c = get_or_create_user(
                "demo.eleve.autoinscrit.showcase@xporadia.ci", primary_role=UserRole.STUDENT,
                first_name="Salimata", last_name="Coulibaly",
            )
            note(c)
            selfreg_child, c = Child.objects.get_or_create(
                user=selfreg_user,
                defaults={
                    "parent": None, "first_name": "Salimata", "last_name": "Coulibaly",
                    "class_level": "Terminale D",
                },
            )
            note(c)
            Enrollment.objects.get_or_create(
                child=selfreg_child, school_class=school_class, defaults={"status": EnrollmentStatus.ACTIVE}
            )

            waiting_parent_user, c = get_or_create_user(
                "demo.parent.enattente.showcase@xporadia.ci", primary_role=UserRole.PARENT,
                first_name="Yacouba", last_name="Coulibaly",
            )
            note(c)
            waiting_parent, c = ParentProfile.objects.get_or_create(
                user=waiting_parent_user, defaults={"subscription_active": True}
            )
            note(c)
            _, c = ChildClaimRequest.objects.get_or_create(
                parent=waiting_parent, child=selfreg_child, defaults={"status": ChildClaimRequestStatus.PENDING}
            )
            note(c)

            # === DM automatiques élève <-> chaque enseignant dédié ===
            # Dans la vraie vie, déclenchée à l'affectation d'un enseignant à
            # une matière ou à l'activation d'un compte élève (voir
            # ensure_teacher_dm_channels) — jamais liée à l'ouverture d'un
            # canal de matière. Sans cet appel ici, les affectations
            # enseignant/matière faites directement en ORM par ce script ne
            # déclenchent jamais ce mécanisme, et aucune DM n'existe alors
            # entre l'élève et un enseignant dédié dont la matière n'a pas
            # encore de canal ouvert — ce qui bloquerait à tort la bascule
            # devoir -> DM et la correction côté enseignant pour ces matières.
            for subject in subjects.values():
                ensure_teacher_dm_channels(subject)

            # === Canaux : classe + une matière ouverte par son enseignant ===
            # Jamais automatique dans la vraie vie (voir create_subject_channel) —
            # ici on simule qu'un enseignant a déjà ouvert le canal de Mathématiques,
            # pour pouvoir tester réellement un canal de matière avec des devoirs
            # publiés dedans ; les autres matières restent volontairement "pas
            # encore ouvertes" (état réel et courant, pas un manque à corriger).
            get_or_create_class_channel(school_class)
            maths_channel = Channel.objects.filter(
                channel_type=ChannelType.SUBJECT, subject=subjects["Mathématiques"]
            ).first()
            if maths_channel is None:
                maths_channel = create_subject_channel(subjects["Mathématiques"], subjects["Mathématiques"].teacher)
                note(True)
            else:
                note(False)

            # === Trimestres (historique, échelles de notation différentes) ===
            term1, c = Term.objects.get_or_create(
                establishment=director, school_year="2025-2026", number=1,
                defaults={"name": "Premier trimestre", "start_date": date(2025, 9, 15), "end_date": date(2025, 12, 19), "is_active": False},
            )
            note(c)
            term2, c = Term.objects.get_or_create(
                establishment=director, school_year="2025-2026", number=2,
                defaults={"name": "Deuxième trimestre", "start_date": date(2026, 1, 5), "end_date": date(2026, 3, 27), "is_active": False},
            )
            note(c)
            term3, c = Term.objects.get_or_create(
                establishment=director, school_year="2025-2026", number=3,
                defaults={"name": "Troisième trimestre", "start_date": date(2026, 4, 13), "end_date": date(2026, 6, 30), "is_active": False},
            )
            note(c)

            # === Évaluations + notes, échelles volontairement variées ===
            # T1 : tout sur /20 (barème standard).
            # T2 : mélange /10 et /40 pour vérifier la normalisation.
            # T3 : mélange /20 et /15, trimestre le plus récent, pas encore de bulletin.
            eval_specs = [
                # (term, subject_name, title, eval_type, max_score, coefficient, score)
                (term1, "Mathématiques", "Devoir 1", EvaluationType.HOMEWORK, 20, 1, Decimal("14.50")),
                (term1, "Mathématiques", "Composition T1", EvaluationType.EXAM, 20, 3, Decimal("12.00")),
                (term1, "Physique-Chimie", "Interro 1", EvaluationType.QUIZ, 20, 1, Decimal("16.00")),
                (term1, "Physique-Chimie", "Composition T1", EvaluationType.EXAM, 20, 3, Decimal("13.50")),
                (term1, "Français", "Dissertation", EvaluationType.EXAM, 20, 2, Decimal("11.00")),
                (term1, "Anglais", "Oral", EvaluationType.QUIZ, 20, 1, Decimal("17.00")),

                (term2, "Mathématiques", "Devoir 2", EvaluationType.HOMEWORK, 10, 1, Decimal("7.50")),
                (term2, "Mathématiques", "Composition T2", EvaluationType.EXAM, 40, 3, Decimal("31.00")),
                (term2, "Physique-Chimie", "Interro 2", EvaluationType.QUIZ, 10, 1, Decimal("8.00")),
                (term2, "Physique-Chimie", "Composition T2", EvaluationType.EXAM, 40, 3, Decimal("29.00")),
                (term2, "Français", "Commentaire", EvaluationType.EXAM, 20, 2, Decimal("13.00")),
                (term2, "Anglais", "Composition T2", EvaluationType.EXAM, 20, 2, Decimal("15.50")),

                (term3, "Mathématiques", "Devoir 3", EvaluationType.HOMEWORK, 20, 1, Decimal("15.00")),
                (term3, "Mathématiques", "Composition T3", EvaluationType.EXAM, 15, 3, Decimal("10.50")),
                (term3, "Physique-Chimie", "Composition T3", EvaluationType.EXAM, 20, 3, Decimal("14.00")),
                (term3, "Français", "Composition T3", EvaluationType.EXAM, 20, 2, Decimal("12.50")),
                # Philosophie n'existe que depuis T3 (Fatou en a pris la
                # charge en même temps que ce script vitrine) : aucune note
                # en T1/T2, jamais touché les bulletins déjà publiés.
                (term3, "Philosophie", "Dissertation blanche", EvaluationType.HOMEWORK, 20, 1, Decimal("13.00")),
                (term3, "Philosophie", "Composition T3", EvaluationType.EXAM, 20, 3, Decimal("11.50")),
            ]
            for term, subject_name, title, eval_type, max_score, coeff, score in eval_specs:
                subject = subjects[subject_name]
                evaluation, c1 = Evaluation.objects.get_or_create(
                    subject=subject, term=term, title=title,
                    defaults={
                        "eval_type": eval_type, "coefficient": coeff, "max_score": max_score,
                        "date": term.start_date + timedelta(days=20), "created_by": subject.teacher,
                    },
                )
                note(c1)
                grade, c2 = Grade.objects.get_or_create(
                    evaluation=evaluation, child=child, defaults={"score": score},
                )
                note(c2)

            # === Bulletins publiés pour T1 et T2 (T3 volontairement sans bulletin) ===
            for term in (term1, term2):
                general_avg = compute_general_average(child, school_class, term)
                if general_avg is None:
                    continue
                rankings = compute_class_rankings(school_class, term)
                my_rank_entry = next((e for e in rankings["ranked"] if e["child"].id == child.id), None)
                report_card, c = ReportCard.objects.get_or_create(
                    child=child, term=term,
                    defaults={
                        "school_class": school_class,
                        "general_average": general_avg,
                        "class_average": rankings["class_average"] or general_avg,
                        "rank": my_rank_entry["rank"] if my_rank_entry else 1,
                        "class_size": rankings["ranked"] and len(rankings["ranked"]) or 1,
                        "homeroom_comment": "Trimestre sérieux, des efforts réguliers à poursuivre.",
                    },
                )
                note(c)
                if c:
                    for subject in subjects.values():
                        subject_avg = compute_subject_average(child, subject, term)
                        SubjectReportEntry.objects.create(
                            report_card=report_card, subject_name=subject.name,
                            subject_average=subject_avg, coefficient=subject.coefficient,
                            teacher_comment="Bon niveau, continuez ainsi." if subject_avg and subject_avg >= 12 else "Peut mieux faire avec plus de régularité.",
                        )
                else:
                    # Bulletin déjà présent mais republié depuis (par ex. via
                    # "Générer et publier les bulletins" côté enseignant, qui
                    # recalcule et vide les appréciations si aucune
                    # SubjectAppreciation n'existe en base) : backfill des
                    # champs texte manquants sans toucher aux moyennes/rang
                    # déjà à jour.
                    if not report_card.homeroom_comment:
                        report_card.homeroom_comment = "Trimestre sérieux, des efforts réguliers à poursuivre."
                        report_card.save(update_fields=["homeroom_comment"])
                        note(True)
                    existing_entries = {e.subject_name: e for e in report_card.subject_entries.all()}
                    for subject in subjects.values():
                        entry = existing_entries.get(subject.name)
                        comment = (
                            "Bon niveau, continuez ainsi."
                            if entry and entry.subject_average and entry.subject_average >= 12
                            else "Peut mieux faire avec plus de régularité."
                        )
                        if entry is None:
                            subject_avg = compute_subject_average(child, subject, term)
                            SubjectReportEntry.objects.create(
                                report_card=report_card, subject_name=subject.name,
                                subject_average=subject_avg, coefficient=subject.coefficient,
                                teacher_comment="Bon niveau, continuez ainsi." if subject_avg and subject_avg >= 12 else "Peut mieux faire avec plus de régularité.",
                            )
                            note(True)
                        elif not entry.teacher_comment:
                            entry.teacher_comment = comment
                            entry.save(update_fields=["teacher_comment"])
                            note(True)

            # === Devoirs dans les trois états ===
            def get_exercise(subject_name, title, kind=ExerciseKind.HOMEWORK, days_ago=3):
                subject = subjects[subject_name]
                vc = VirtualClass.objects.get(subject=subject)
                deadline = timezone.now() - timedelta(days=days_ago) + timedelta(days=7)
                exercise, created = Exercise.objects.get_or_create(
                    virtual_class=vc, title=title,
                    defaults={
                        "kind": kind, "instructions": f"Consignes pour « {title} ».",
                        "status": ExerciseStatus.PUBLISHED, "deadline": deadline,
                        "published_at": timezone.now() - timedelta(days=days_ago),
                    },
                )
                return exercise, created

            ex_maths, c = get_exercise("Mathématiques", "Exercices sur les suites numériques")
            note(c)  # en cours : publié, sans soumission
            if not Message.objects.filter(channel=maths_channel, exercise_id=ex_maths.id).exists():
                Message.objects.create(channel=maths_channel, author=subjects["Mathématiques"].teacher, exercise_id=ex_maths.id)
                note(True)
            else:
                note(False)

            ex_pc, c = get_exercise("Physique-Chimie", "TP : lois de Newton")
            note(c)
            sub_pc = Submission.objects.filter(exercise=ex_pc, child=child).first()
            if sub_pc is None:
                sub_pc = Submission.objects.create(
                    exercise=ex_pc, child=child,
                    submitted_by=student_user, content="Voici mon compte-rendu de TP.",
                    status=SubmissionStatus.SUBMITTED,
                )
                note(True)
            else:
                note(False)  # soumis : soumission sans note
            if not sub_pc.attachments:
                # Plusieurs pièces jointes réelles (une image, un PDF) — une
                # soumission à une seule pièce jointe ne teste pas le rendu
                # en liste ni le mélange de types. Vérifié séparément de la
                # création : une soumission existant déjà d'une exécution
                # antérieure du seed (avant l'ajout de ce champ) doit aussi
                # être complétée, pas seulement une toute nouvelle.
                sub_pc.attachments = [
                    save_demo_attachment("schema_experience.jpg", make_demo_cover_bytes(), "image/jpeg", "submission_attachments"),
                    save_demo_attachment("compte_rendu_tp.pdf", make_demo_pdf_bytes("TP lois de Newton"), "application/pdf", "submission_attachments"),
                ]
                sub_pc.save(update_fields=["attachments"])
                note(True)
            else:
                note(False)

            ex_francais, c = get_exercise("Français", "Dissertation sur Une si longue lettre", kind=ExerciseKind.EXAM, days_ago=10)
            note(c)
            sub_francais, c2 = Submission.objects.get_or_create(
                exercise=ex_francais, child=child,
                defaults={
                    "submitted_by": student_user, "content": "Dissertation complète en pièce jointe.",
                    "status": SubmissionStatus.GRADED, "grade": Decimal("14.00"),
                    "feedback": "Bonne analyse, structure claire. Attention à la conclusion, trop courte.",
                    "graded_at": timezone.now() - timedelta(days=2), "graded_by": subjects["Français"].teacher,
                },
            )
            note(c2)  # corrigé

            ex_anglais, c = get_exercise("Anglais", "Essay: My future career", days_ago=8)
            note(c)
            sub_anglais, c2 = Submission.objects.get_or_create(
                exercise=ex_anglais, child=child,
                defaults={
                    "submitted_by": student_user, "content": "My essay is attached.",
                    "status": SubmissionStatus.GRADED, "grade": Decimal("16.50"),
                    "feedback": "Very good vocabulary, well done!",
                    "graded_at": timezone.now() - timedelta(days=1), "graded_by": subjects["Anglais"].teacher,
                },
            )
            note(c2)  # corrigé (2e matière, pour la variété)

            ex_philo, c = get_exercise("Philosophie", "Dissertation : la liberté est-elle une illusion ?", kind=ExerciseKind.EXAM, days_ago=4)
            note(c)  # en cours : publié, sans soumission — Fatou a une copie réelle à voir arriver

            # === Messagerie : DM avec un enseignant, DM avec un camarade ===
            dm_teacher = get_or_create_direct_channel(student_user, subjects["Mathématiques"].teacher)
            if dm_teacher.messages.count() == 0:
                Message.objects.create(
                    channel=dm_teacher, author=student_user,
                    body="Bonjour Monsieur, je n'ai pas compris l'exercice 3 sur les suites, vous pouvez m'aider ?",
                )
                Message.objects.create(
                    channel=dm_teacher, author=subjects["Mathématiques"].teacher,
                    body="Bonjour Kevin, regarde la formule du terme général : reprends ton cours page 12, ça devrait débloquer.",
                    attachments=[
                        save_demo_attachment("formule_terme_general.jpg", make_demo_cover_bytes(), "image/jpeg", "message_attachments"),
                    ],
                )
                Message.objects.create(
                    channel=dm_teacher, author=student_user,
                    body="Ah oui, merci, je vois mieux maintenant !",
                )
                note(True)
            else:
                note(False)
                teacher_answer = dm_teacher.messages.filter(
                    author=subjects["Mathématiques"].teacher, attachments=[]
                ).first()
                if teacher_answer:
                    # Complète une conversation déjà créée avant l'ajout de
                    # la pièce jointe à ce message précis.
                    teacher_answer.attachments = [
                        save_demo_attachment("formule_terme_general.jpg", make_demo_cover_bytes(), "image/jpeg", "message_attachments"),
                    ]
                    teacher_answer.save(update_fields=["attachments"])
                    note(True)
                else:
                    note(False)

            dm_classmate = get_or_create_direct_channel(student_user, classmate_user)
            if dm_classmate.messages.count() == 0:
                Message.objects.create(channel=dm_classmate, author=classmate_user, body="Salut, t'as fini le devoir de maths ?")
                Message.objects.create(channel=dm_classmate, author=student_user, body="Pas encore, je bloque sur l'exo 3 aussi !")
                note(True)
            else:
                note(False)

            # === Bibliothèque : formats et tailles variés ===
            library_specs = [
                dict(title="Cours complet : Suites numériques", resource_type=ResourceType.COURSE,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Mathématiques",
                     file_url="", has_pdf=True, has_cover=True, file_size_kb=850),
                dict(title="Fiche de révision : Lois de Newton", resource_type=ResourceType.REVISION,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Physique-Chimie",
                     file_url="", has_pdf=True, has_cover=False, file_size_kb=210),
                dict(title="Une si longue lettre : Mariama Bâ (texte intégral)", resource_type=ResourceType.EXAM,
                     category=ResourceCategory.LITERATURE, level=SchoolLevel.TERMINALE, subject="Français",
                     file_url="https://example.com/une-si-longue-lettre.pdf", has_pdf=False, has_cover=True, file_size_kb=0),
                dict(title="Annale BAC 2024 : Anglais LV1", resource_type=ResourceType.EXAM,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Anglais",
                     file_url="https://example.com/annale-anglais-2024.pdf", has_pdf=False, has_cover=False, file_size_kb=0),
                dict(title="Corrigé : Composition Physique-Chimie T2", resource_type=ResourceType.SOLUTION,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Physique-Chimie",
                     file_url="", has_pdf=True, has_cover=True, file_size_kb=390),
            ]
            # Renommage correctif : ces deux titres portaient un tiret
            # cadratin (règle d'interface interdisant ce caractère) avant
            # d'être corrigés ici — sans ce renommage, une base déjà seedée
            # avec l'ancien titre ne serait jamais retrouvée par le
            # get_or_create ci-dessous (clé = title) et créerait un doublon
            # au lieu de corriger la ressource existante en place.
            title_renames = {
                "Une si longue lettre — Mariama Bâ (texte intégral)": "Une si longue lettre : Mariama Bâ (texte intégral)",
                "Annale BAC 2024 — Anglais LV1": "Annale BAC 2024 : Anglais LV1",
            }
            for old_title, new_title in title_renames.items():
                LibraryResource.objects.filter(establishment=director, title=old_title).update(title=new_title)

            for spec in library_specs:
                resource, c = LibraryResource.objects.get_or_create(
                    establishment=director, title=spec["title"],
                    defaults={
                        "description": f"Ressource de démonstration pour {spec['subject']}.",
                        "resource_type": spec["resource_type"], "category": spec["category"],
                        "level": spec["level"], "subject": spec["subject"],
                        "file_url": spec["file_url"],
                        "tags": [spec["subject"].lower()],
                        "author": subjects.get(spec["subject"]).teacher if spec["subject"] in subjects else director_user,
                        "is_contributed": False,
                        "moderation_status": ModerationStatus.APPROVED,
                    },
                )
                # PDF hébergé et couverture doivent être de VRAIS fichiers
                # enregistrés sur disque, pas juste des booléens — sans quoi
                # une ressource "has_pdf" viole en silence
                # LibraryResource.clean() (ni PDF ni lien) et le
                # visualisateur PDF in-app n'a rien de réel à ouvrir.
                needs_save = False
                if spec["has_pdf"] and not resource.pdf_file:
                    resource.pdf_file.save(
                        f"{resource.id}.pdf", ContentFile(make_demo_pdf_bytes(spec["title"])), save=False
                    )
                    needs_save = True
                if spec["has_cover"] and not resource.cover_image:
                    resource.cover_image.save(
                        f"{resource.id}.jpg", ContentFile(make_demo_cover_bytes()), save=False
                    )
                    needs_save = True
                if needs_save:
                    resource.file_size_kb = max(1, resource.pdf_file.size // 1024) if resource.pdf_file else 0
                    resource.save()
                note(c or needs_save)

            # === Emploi du temps + créneau personnel + événement ===
            slot_specs = [
                ("Mathématiques", 0, time(8, 0), time(9, 0)),
                ("Physique-Chimie", 1, time(9, 0), time(10, 30)),
                ("Français", 2, time(10, 0), time(11, 0)),
                ("Anglais", 3, time(14, 0), time(15, 0)),
                ("Mathématiques", 4, time(8, 0), time(9, 30)),
            ]
            for subject_name, weekday, start, end in slot_specs:
                _, c = TimetableSlot.objects.get_or_create(
                    school_class=school_class, subject=subjects[subject_name], weekday=weekday,
                    start_time=start, defaults={"end_time": end, "room": "Salle 12"},
                )
                note(c)

            today = timezone.localdate()
            personal_block, c = PersonalScheduleBlock.objects.get_or_create(
                child=child, weekday=today.weekday(), start_time=time(18, 0),
                defaults={
                    "end_time": time(19, 0), "title": "Révision maths du soir",
                    "subject": subjects["Mathématiques"], "valid_from": today - timedelta(days=30),
                },
            )
            note(c)

            # Exception ponctuelle sur UNE occurrence du bloc personnel (la
            # prochaine à cette date) — la règle récurrente continue
            # normalement les autres semaines, seule cette date change.
            next_occurrence = today + timedelta(days=7)
            _, c = PersonalScheduleException.objects.get_or_create(
                block=personal_block, date=next_occurrence,
                defaults={"title": "Révision maths décalée (contrôle le lendemain)", "start_time": time(19, 30), "end_time": time(20, 30)},
            )
            note(c)

            _, c = EstablishmentEvent.objects.get_or_create(
                establishment=director, school_class=school_class, event_type=EventType.MEETING,
                title="Réunion parents-professeurs", date=today + timedelta(days=10),
                defaults={
                    "start_time": time(17, 0), "end_time": time(19, 0),
                    "audience": [EventAudience.PARENTS, EventAudience.TEACHERS],
                    "created_by": homeroom_user,
                },
            )
            note(c)

            # Jour férié déclaré sur une date normalement scolaire (lundi,
            # dans la plage du deuxième trimestre) — doit neutraliser le
            # cours de Mathématiques ce jour précis dans l'agenda, sans
            # requalifier la date en vacance pour le reste du système.
            holiday_event, c = EstablishmentEvent.objects.get_or_create(
                establishment=director, school_class=school_class, event_type=EventType.HOLIDAY,
                title="Fête nationale", date=date(2026, 2, 2),
                defaults={"audience": [EventAudience.STUDENTS, EventAudience.PARENTS], "created_by": homeroom_user},
            )
            note(c)
            # La notification "jour férié" n'est un effet de bord que de
            # ClassEventListCreateView.post() (jamais du modèle) — sans cet
            # appel explicite ici, un jour férié créé directement en ORM par
            # ce script ne notifierait jamais personne, alors que c'est l'un
            # des types de notification que ce jeu de données doit
            # démontrer. Backfill couvert aussi pour un événement déjà
            # présent d'une exécution précédente à ce correctif.
            if not Notification.objects.filter(
                user=student_user, notif_type=NotificationType.HOLIDAY_DECLARED,
                data__event_id=str(holiday_event.id),
            ).exists():
                _notify_holiday_declared(holiday_event)
                note(True)

            # === Vie & objectifs ===
            # related_subjects doit compter au moins 3 matières ayant une
            # moyenne réelle au dernier bulletin publié : le radar de
            # compétences du tableau de bord élève exige >= 3 axes pour
            # s'afficher (radarAxes.length >= 3 côté frontend).
            life_goal, created_lg = LifeGoal.objects.get_or_create(
                child=child,
                defaults={
                    "description": "Devenir ingénieur en énergies renouvelables pour contribuer à l'accès à "
                                   "l'électricité en zone rurale.",
                    "related_subjects": ["Mathématiques", "Physique-Chimie", "Français"],
                },
            )
            note(created_lg)
            if not created_lg and len(life_goal.related_subjects or []) < 3:
                life_goal.related_subjects = ["Mathématiques", "Physique-Chimie", "Français"]
                life_goal.save(update_fields=["related_subjects"])
                note(True)

            bucket_specs = [
                ("Obtenir le BAC avec mention", False),
                ("Visiter le barrage de Soubré", True),
                ("Participer à un concours de robotique", False),
            ]
            for title, is_done in bucket_specs:
                _, c = BucketListItem.objects.get_or_create(
                    child=child, title=title,
                    defaults={"is_done": is_done, "done_at": timezone.now() - timedelta(days=60) if is_done else None},
                )
                note(c)

            # === Fil d'actualité : publications d'un enseignant suivi ===
            # Alimente le bloc "activité sociale récente" du tableau de bord,
            # qui n'affiche que les publications des auteurs suivis.
            _, c = Follow.objects.get_or_create(follower=student_user, followed=subjects["Mathématiques"].teacher)
            note(c)
            post_specs = [
                "Petit rappel pour la classe : la composition de mathématiques du T2 approche, révisez bien les suites numériques.",
                "Ravi de voir autant de progrès ce trimestre, continuez ainsi !",
            ]
            for body in post_specs:
                _, c = Post.objects.get_or_create(author=subjects["Mathématiques"].teacher, body=body)
                note(c)

            # === Enseignante : gestion de classe avancée ===
            # Classe soeur du même établissement/filière — sert de
            # destination réelle lors d'une promotion de fin d'année,
            # sans quoi l'écran n'aurait aucune classe cible à proposer.
            sibling_class, c = SchoolClass.objects.get_or_create(
                track=track, name="Terminale D1", school_year="2025-2026",
            )
            note(c)

            # Délégation de la gestion des emplois du temps par la
            # directrice à Fatou (déjà titulaire) — teste my-delegations et
            # débloque timetable-editor pour elle sur tout l'établissement.
            _, c = TaskDelegation.objects.get_or_create(
                establishment=director, teacher=homeroom_user, task=DelegatedTask.TIMETABLE,
            )
            note(c)

            # === Enseignante : certification (niveau acquis + niveau suivant à tenter) ===
            bronze_module, c = TrainingModule.objects.get_or_create(
                title="Fondamentaux pédagogiques (vitrine)",
                defaults={
                    "category": ModuleCategory.PEDAGOGY,
                    "description": "Les bases de la pédagogie active : différenciation, structuration de séquence.",
                    "objectives": ["Différencier pédagogie active et transmissive", "Structurer une séquence complète"],
                    "duration_hours": 6, "price": 15000, "points": 10,
                    "target_level": CertificationLevel.BRONZE,
                },
            )
            note(c)
            bronze_questions = [
                ("Qu'est-ce que la pédagogie active ?", QuestionType.MCQ,
                 ["Une méthode centrée sur l'enseignant", "Une méthode où l'élève construit son savoir", "Un simple exposé magistral"],
                 "Une méthode où l'élève construit son savoir"),
                ("Une séquence pédagogique doit toujours commencer par une évaluation sommative.", QuestionType.TF, [], "false"),
            ]
            for text, qtype, options, correct in bronze_questions:
                _, c = ExamQuestion.objects.get_or_create(
                    module=bronze_module, text=text,
                    defaults={"question_type": qtype, "options": options, "correct_answer": correct,
                              "difficulty": DifficultyLevel.EASY, "points": 1},
                )
                note(c)

            bronze_attempt, c = ExamAttempt.objects.get_or_create(
                teacher=homeroom_user, module=bronze_module, is_online=True,
                defaults={
                    "answers": {}, "score_auto": Decimal("85.00"), "score_total": Decimal("85.00"),
                    "status": AttemptStatus.PASSED,
                    "submitted_at": timezone.now() - timedelta(days=200),
                    "graded_at": timezone.now() - timedelta(days=200),
                },
            )
            note(c)
            _, c = Certification.objects.get_or_create(
                teacher=homeroom_user, module=bronze_module,
                defaults={
                    "attempt": bronze_attempt, "level": CertificationLevel.BRONZE,
                    "points_awarded": bronze_module.points, "score_total": Decimal("85.00"),
                    "qr_code": f"XPD-SHOWCASE-BRONZE-{homeroom_user.id}",
                    "expires_at": date.today() + timedelta(days=730),
                },
            )
            note(c)

            # Module du niveau suivant : questions présentes, mais AUCUNE
            # tentative — laissé volontairement ouvert pour tester
            # l'examen en ligne réel (teacher/online-exam) en conditions
            # vraies plutôt que de le pré-remplir.
            silver_module, c = TrainingModule.objects.get_or_create(
                title="Différenciation pédagogique avancée (vitrine)",
                defaults={
                    "category": ModuleCategory.DIDACTICS,
                    "description": "Concevoir des parcours différenciés pour des classes hétérogènes.",
                    "objectives": ["Adapter une séquence à des niveaux hétérogènes", "Concevoir une évaluation différenciée"],
                    "duration_hours": 8, "price": 25000, "points": 15,
                    "target_level": CertificationLevel.SILVER,
                },
            )
            note(c)
            silver_questions = [
                ("La différenciation pédagogique consiste à...", QuestionType.MCQ,
                 ["Donner le même exercice à tous", "Adapter les tâches aux besoins de chaque élève", "Ne noter que les meilleurs"],
                 "Adapter les tâches aux besoins de chaque élève"),
                ("Décrivez une situation de différenciation vécue dans votre classe.", QuestionType.OPEN, [], ""),
            ]
            for text, qtype, options, correct in silver_questions:
                _, c = ExamQuestion.objects.get_or_create(
                    module=silver_module, text=text,
                    defaults={"question_type": qtype, "options": options, "correct_answer": correct,
                              "difficulty": DifficultyLevel.MEDIUM, "points": 1},
                )
                note(c)

            # === Enseignante : formation continue (session à venir, payée) ===
            trainer_user, c = get_or_create_user(
                "demo.formateur.showcase@xporadia.ci", primary_role=UserRole.TRAINER,
                first_name="Konan", last_name="Assouan",
            )
            note(c)
            training_session, c = TrainingSession.objects.get_or_create(
                module=silver_module, trainer=trainer_user, city="Abidjan",
                date=timezone.localdate() + timedelta(days=25),
                defaults={
                    "location": "Centre de formation Xporadia, Cocody",
                    "start_time": time(9, 0), "end_time": time(16, 0),
                    "capacity": 25, "status": CertSessionStatus.PLANNED,
                },
            )
            note(c)
            session_enrollment, c = SessionEnrollment.objects.get_or_create(
                session=training_session, teacher=homeroom_user,
            )
            if c:
                session_payment = Payment.objects.create(
                    user=homeroom_user, amount=silver_module.price, operator=MobileOperator.ORANGE,
                    phone_number="0700000001", payment_type=PaymentType.TRAINING, status=PayStatus.COMPLETED,
                    tx_ref=f"XPD-SHOWCASE-TRAINING-{homeroom_user.id}",
                    completed_at=timezone.now() - timedelta(days=5),
                )
                session_enrollment.payment_status = "paid"
                session_enrollment.payment = session_payment
                session_enrollment.save(update_fields=["payment_status", "payment"])
                training_session.enrolled_count += 1
                training_session.save(update_fields=["enrolled_count"])
            note(c)

            # === Enseignante : emploi (candidature en attente + recrutement confirmé) ===
            # Second établissement, distinct de celui de la classe vitrine —
            # une candidature ET un recrutement déjà confirmé ailleurs sont
            # deux états réels et compatibles (vacations chez un autre
            # employeur, en plus de son poste de titulaire).
            second_director_user, c = get_or_create_user(
                "demo.directeur2.showcase@xporadia.ci", primary_role=UserRole.DIRECTOR,
                first_name="Yves", last_name="N'Guessan",
            )
            note(c)
            second_director, c = DirectorProfile.objects.get_or_create(
                user=second_director_user,
                defaults={"school_name": "Collège Passerelle", "address": "Yopougon, Abidjan", "is_partner": True},
            )
            note(c)

            job_listing, c = JobListing.objects.get_or_create(
                school=second_director_user, title="Professeur(e) de Philosophie, vacation",
                defaults={
                    "subject": "Philosophie", "levels": ["Terminale"], "contract_type": ContractType.VACATION,
                    "salary_min": 4000, "salary_max": 6000, "cert_level_required": CertificationLevel.BRONZE,
                    "description": "Vacations de philosophie pour la Terminale, deux soirs par semaine.",
                    "city": "Abidjan", "commune": "Yopougon", "status": JobStatus.ACTIVE,
                    "published_at": timezone.now() - timedelta(days=12),
                    "expires_at": timezone.localdate() + timedelta(days=45),
                },
            )
            note(c)
            _, c = JobApplication.objects.get_or_create(
                teacher=homeroom_user, listing=job_listing,
                defaults={"cover_letter": "Titulaire certifiée Bronze, disponible en soirée pour des vacations."},
            )
            note(c)

            recruitment, c = Recruitment.objects.get_or_create(
                school=second_director_user, teacher=homeroom_user,
                defaults={
                    "contract_type": ContractType.CDD, "hourly_rate_teacher": 5000, "hourly_rate_billed": 6000,
                    "commission_rate": Decimal("10.00"), "payment_status": RecruitmentPaymentStatus.PAID,
                },
            )
            note(c)

            # === Enseignante : heures déclarées, clôture de paie, portefeuille crédité ===
            # Un mois déjà clôturé (le mois dernier) — heures validées par le
            # directeur, converties en ligne de paie, qui crédite le
            # portefeuille : sans cette chaîne complète, "Portefeuille"
            # afficherait un solde à zéro malgré un recrutement confirmé.
            last_month_ref = timezone.localdate().replace(day=1) - timedelta(days=1)
            worked_hours_specs = [
                (last_month_ref.replace(day=4), Decimal("4.00")),
                (last_month_ref.replace(day=11), Decimal("6.00")),
                (last_month_ref.replace(day=18), Decimal("5.00")),
            ]
            total_hours = sum(h for _, h in worked_hours_specs)
            worked_hours_rows = []
            for wdate, hours in worked_hours_specs:
                wh, c = WorkedHours.objects.get_or_create(
                    recruitment=recruitment, date=wdate,
                    defaults={
                        "hours": hours, "note": "Vacations de philosophie", "status": WorkedHoursStatus.APPROVED,
                        "reviewed_by": second_director_user, "reviewed_at": timezone.now() - timedelta(days=20),
                    },
                )
                note(c)
                worked_hours_rows.append(wh)

            gross_amount = int(total_hours * recruitment.hourly_rate_teacher)
            billed_amount = int(total_hours * recruitment.hourly_rate_billed)
            payroll_entry, c = PayrollEntry.objects.get_or_create(
                recruitment=recruitment, period_year=last_month_ref.year, period_month=last_month_ref.month,
                defaults={
                    "total_hours": total_hours,
                    "hourly_rate_teacher": recruitment.hourly_rate_teacher,
                    "hourly_rate_billed": recruitment.hourly_rate_billed,
                    "gross_amount": gross_amount, "billed_amount": billed_amount,
                    "xporadia_margin": billed_amount - gross_amount,
                },
            )
            note(c)
            if c:
                WorkedHours.objects.filter(id__in=[wh.id for wh in worked_hours_rows]).update(payroll_entry=payroll_entry)
            _, c = WalletTransaction.objects.get_or_create(
                payroll_entry=payroll_entry, defaults={"teacher": homeroom_user, "amount": gross_amount},
            )
            note(c)

            # Un mois en cours, pas encore clôturé — heures déclarées mais
            # encore en attente de validation par le directeur, pour tester
            # ce second état (distinct du mois déjà payé ci-dessus).
            _, c = WorkedHours.objects.get_or_create(
                recruitment=recruitment, date=timezone.localdate() - timedelta(days=2),
                defaults={"hours": Decimal("3.00"), "note": "Vacations de philosophie", "status": WorkedHoursStatus.PENDING},
            )
            note(c)

            # === Enseignante : portefeuille (paiement réel, distinct de la formation) ===
            _, c = Payment.objects.get_or_create(
                tx_ref=f"XPD-SHOWCASE-TUTORING-{homeroom_user.id}",
                defaults={
                    "user": homeroom_user, "amount": 7500, "operator": MobileOperator.WAVE,
                    "phone_number": "0700000002", "payment_type": PaymentType.TUTORING,
                    "status": PayStatus.COMPLETED, "completed_at": timezone.now() - timedelta(days=15),
                },
            )
            note(c)

        self.stdout.write(self.style.SUCCESS(
            f"Écosystème vitrine prêt (mot de passe commun : {DEMO_PASSWORD}) — "
            f"élève : demo.eleve.showcase@xporadia.ci · "
            f"enseignante (titulaire + Philosophie) : demo.titulaire.showcase@xporadia.ci · "
            f"parent : demo.parent.showcase@xporadia.ci "
            f"(objets créés : {created_counts['created']}, déjà présents : {created_counts['existing']})."
        ))
