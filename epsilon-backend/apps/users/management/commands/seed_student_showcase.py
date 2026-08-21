"""
Xporadia — seed_student_showcase

Jeu de données de démonstration dédié à UN élève vitrine, couvrant tous
les états possibles du profil élève actuel : classe avec plusieurs
matières et enseignants, historique de plusieurs trimestres avec des
notes sur des échelles différentes, devoirs dans les trois états (en
cours, soumis, corrigé), messagerie (DM avec un enseignant, DM avec un
camarade), bibliothèque variée, bulletins publiés, agenda (emploi du
temps + créneaux personnels + un événement d'établissement), et le module
Vie & objectifs.

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
    TimetableSlot,
    Track,
)
from apps.academics.views import _notify_holiday_declared
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
from apps.student_life.models import BucketListItem, LifeGoal
from apps.users.models import Child, ChildClaimRequest, ChildClaimRequestStatus, DirectorProfile, ParentProfile, User, UserRole
from apps.virtual_classes.models import Exercise, ExerciseKind, ExerciseStatus, Submission, SubmissionStatus, VirtualClass

DEMO_PASSWORD = "Xporadia2026!"


def get_or_create_user(email, **fields):
    # get_or_create() n'appelle jamais UserManager.create_user() — le
    # is_verified=True qu'il applique par défaut est donc perdu ici,
    # laissant l'utilisateur bloqué derrière l'écran de vérification par
    # code OTP à la première connexion. Un compte de démonstration doit
    # être immédiatement utilisable : forcé explicitement ci-dessous.
    user, created = User.objects.get_or_create(
        email=email, defaults={"password": "!", "is_verified": True, **fields}
    )
    if created:
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
    elif not user.is_verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])
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
    help = "Jeu de démonstration complet et idempotent pour un élève vitrine (profil élève au complet)."

    def handle(self, *args, **options):
        created_counts = {"created": 0, "existing": 0}

        def note(created):
            created_counts["created" if created else "existing"] += 1

        with transaction.atomic():
            # === Établissement + structure ===
            director_user, c = get_or_create_user(
                "demo.directeur.showcase@xporadia.ci", primary_role=UserRole.DIRECTOR,
                first_name="Solange", last_name="Bakayoko",
                # is_documents_validated=False par défaut (validé par un
                # administrateur Xporadia après inscription réelle) —
                # l'établissement n'apparaîtrait sinon jamais dans
                # l'annuaire public (EstablishmentDirectoryViewSet), donc
                # jamais trouvable depuis "Rejoindre mon établissement".
                is_documents_validated=True,
            )
            note(c)
            if not director_user.is_documents_validated:
                director_user.is_documents_validated = True
                director_user.save(update_fields=["is_documents_validated"])
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
                dict(title="Une si longue lettre — Mariama Bâ (texte intégral)", resource_type=ResourceType.EXAM,
                     category=ResourceCategory.LITERATURE, level=SchoolLevel.TERMINALE, subject="Français",
                     file_url="https://example.com/une-si-longue-lettre.pdf", has_pdf=False, has_cover=True, file_size_kb=0),
                dict(title="Annale BAC 2024 — Anglais LV1", resource_type=ResourceType.EXAM,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Anglais",
                     file_url="https://example.com/annale-anglais-2024.pdf", has_pdf=False, has_cover=False, file_size_kb=0),
                dict(title="Corrigé : Composition Physique-Chimie T2", resource_type=ResourceType.SOLUTION,
                     category=ResourceCategory.ACADEMIC, level=SchoolLevel.TERMINALE, subject="Physique-Chimie",
                     file_url="", has_pdf=True, has_cover=True, file_size_kb=390),
            ]
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

        self.stdout.write(self.style.SUCCESS(
            f"Élève vitrine prêt — demo.eleve.showcase@xporadia.ci / {DEMO_PASSWORD} "
            f"(objets créés : {created_counts['created']}, déjà présents : {created_counts['existing']})."
        ))
