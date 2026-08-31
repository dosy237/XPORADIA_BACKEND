from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Child, Enrollment, EnrollmentStatus, SchoolClass, Subject
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import UserRole

from . import services
from .models import (
    Evaluation,
    Grade,
    JoinRequestStatus,
    EstablishmentJoinRequest,
    ReportCard,
    ReportCardSanction,
    SubjectAppreciation,
    SubjectReportEntry,
    Term,
)
from .serializers import (
    BulkGradeEntrySerializer,
    EvaluationSerializer,
    GradeSerializer,
    JoinRequestSerializer,
    ReportCardSerializer,
    TermSerializer,
)


def _require_class_manage_access(school_class, user):
    """Titulaire de la classe OU directeur de l'établissement — même
    principe que apps.academics.views._require_roster_access pour le
    passage de classe en masse : le titulaire n'est jamais exclu au
    profit du seul directeur."""
    if school_class.homeroom_teacher_id == user.id:
        return
    if user.has_role(UserRole.DIRECTOR) and school_class.track.department.establishment.user_id == user.id:
        return
    raise PermissionDenied("Réservé au titulaire de cette classe ou au directeur de l'établissement.")


def _require_class_view_access(school_class, user):
    """Qui peut CONSULTER les informations d'une classe liées aux
    bulletins (trimestres disponibles, bulletins déjà publiés) : le
    titulaire, N'IMPORTE QUEL enseignant dédié d'une matière de cette
    classe, ou le directeur. Plus large que _require_class_manage_access
    (réservée à la génération/publication elle-même)."""
    if school_class.homeroom_teacher_id == user.id:
        return
    if user.has_role(UserRole.DIRECTOR) and school_class.track.department.establishment.user_id == user.id:
        return
    if Subject.objects.filter(school_class=school_class, teacher_id=user.id).exists():
        return
    raise PermissionDenied("Réservé au titulaire, à un enseignant de cette classe, ou au directeur.")


def _require_report_card_view_access(report_card, user):
    """Qui peut consulter/télécharger le PDF d'un bulletin déjà publié :
    l'élève lui-même, son parent, le titulaire de la classe, N'IMPORTE
    QUEL enseignant dédié d'une matière de cette classe (pas seulement le
    titulaire — un enseignant a besoin de voir le bulletin complet de ses
    élèves), et le directeur de l'établissement. Volontairement plus
    large que _require_class_manage_access (réservée à la génération)."""
    child = report_card.child
    if child.user_id == user.id:
        return
    if child.parent_id and child.parent.user_id == user.id:
        return
    school_class = report_card.school_class
    if school_class.homeroom_teacher_id == user.id:
        return
    if Subject.objects.filter(school_class=school_class, teacher_id=user.id).exists():
        return
    if user.has_role(UserRole.DIRECTOR) and school_class.track.department.establishment.user_id == user.id:
        return
    raise PermissionDenied("Vous n'avez pas accès à ce bulletin.")


def _require_director_establishment(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux établissements.")
    from apps.users.models import DirectorProfile

    try:
        return user.director_profile
    except DirectorProfile.DoesNotExist:
        raise PermissionDenied("Aucun établissement associé à ce compte.")


def _require_join_request_access(user):
    """Directeur de l'établissement, OU enseignant à qui la gestion des
    demandes de rattachement a été déléguée (voir apps.academics.models.
    TaskDelegation) — jamais mis en cache, une révocation coupe l'accès
    immédiatement, même principe que _require_timetable_write_access côté
    emploi du temps. Ne couvre jamais la gestion des trimestres, qui reste
    strictement director-only via _require_director_establishment."""
    from apps.users.models import DirectorProfile

    try:
        return user.director_profile
    except DirectorProfile.DoesNotExist:
        pass

    from apps.academics.models import DelegatedTask, TaskDelegation

    delegation = TaskDelegation.objects.filter(
        teacher=user, task=DelegatedTask.JOIN_REQUESTS
    ).select_related("establishment").first()
    if delegation:
        return delegation.establishment

    raise PermissionDenied(
        "Réservé au directeur de l'établissement, ou à un enseignant délégué pour les rattachements."
    )


def _require_subject_teacher(subject, user):
    """Seul l'enseignant dédié de CETTE matière peut y créer des
    évaluations et y saisir des notes — jamais le titulaire de la classe
    à sa place (sauf s'il est lui-même l'enseignant dédié de la matière),
    cohérent avec \"chaque enseignant saisit pour sa propre matière\"."""
    if subject.teacher_id != user.id:
        raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")


class TermListCreateView(generics.ListCreateAPIView):
    """Trimestres de l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer
    pagination_class = None

    def get_queryset(self):
        establishment = _require_director_establishment(self.request.user)
        return Term.objects.filter(establishment=establishment)

    def perform_create(self, serializer):
        establishment = _require_director_establishment(self.request.user)
        serializer.save(establishment=establishment)


class TermDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer

    def get_queryset(self):
        establishment = _require_director_establishment(self.request.user)
        return Term.objects.filter(establishment=establishment)


class MyActiveTermView(APIView):
    """Trimestre en cours de l'établissement d'une classe donnée —
    alimente les écrans de saisie enseignant sans qu'ils aient à choisir
    manuellement le bon trimestre à chaque fois."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id):
        try:
            school_class = SchoolClass.objects.select_related(
                "track__department__establishment"
            ).get(id=class_id)
        except SchoolClass.DoesNotExist:
            raise Http404
        establishment = school_class.track.department.establishment
        term = Term.objects.filter(establishment=establishment, is_active=True).first()
        if not term:
            return Response({"detail": "Aucun trimestre actif pour cet établissement."}, status=404)
        return Response(TermSerializer(term).data)


class EvaluationListCreateView(generics.ListCreateAPIView):
    """Évaluations d'une matière — créées et consultées par son enseignant
    dédié uniquement."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EvaluationSerializer
    pagination_class = None

    def get_subject(self):
        subject = get_object_or_404(Subject, pk=self.kwargs["subject_id"])
        _require_subject_teacher(subject, self.request.user)
        return subject

    def get_queryset(self):
        return Evaluation.objects.filter(subject=self.get_subject()).select_related("subject")

    def perform_create(self, serializer):
        serializer.save(subject=self.get_subject(), created_by=self.request.user)


class EvaluationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EvaluationSerializer

    def get_queryset(self):
        return Evaluation.objects.select_related("subject")

    def get_object(self):
        evaluation = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        _require_subject_teacher(evaluation.subject, self.request.user)
        return evaluation


def _save_grade(evaluation, child_id, score, is_excused, user):
    """Crée ou met à jour une note en conservant qui l'a saisie la
    première fois (`created_by`, jamais réécrit ensuite) et qui l'a
    modifiée en dernier (`updated_by`, `graded_at` déjà auto_now) — seul
    point d'écriture de Grade, utilisé par les deux écrans de saisie
    (évaluation seule et grille multi-évaluations)."""
    grade, created = Grade.objects.get_or_create(
        evaluation=evaluation, child_id=child_id,
        defaults={"score": score, "is_excused": is_excused, "created_by": user, "updated_by": user},
    )
    if not created:
        grade.score = score
        grade.is_excused = is_excused
        grade.updated_by = user
        grade.save(update_fields=["score", "is_excused", "updated_by", "graded_at"])
    return grade


class EvaluationGradesView(APIView):
    """Saisie en lot des notes d'une évaluation — GET renvoie tout
    l'effectif de la classe avec la note existante si déjà saisie (jamais
    besoin de redemander la liste séparément), POST enregistre tout le
    lot en une seule requête plutôt qu'un appel par élève."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_evaluation(self, evaluation_id, user):
        evaluation = get_object_or_404(Evaluation.objects.select_related("subject"), pk=evaluation_id)
        _require_subject_teacher(evaluation.subject, user)
        return evaluation

    def get(self, request, evaluation_id):
        evaluation = self._get_evaluation(evaluation_id, request.user)
        enrollments = services.active_enrollments(evaluation.subject.school_class)
        existing_grades = {
            g.child_id: g for g in Grade.objects.filter(evaluation=evaluation)
        }
        roster = []
        for enrollment in enrollments:
            grade = existing_grades.get(enrollment.child_id)
            roster.append({
                "child": enrollment.child.id,
                "child_first_name": enrollment.child.first_name,
                "child_last_name": enrollment.child.last_name,
                "score": grade.score if grade else None,
                "is_excused": grade.is_excused if grade else False,
            })
        return Response(roster)

    def post(self, request, evaluation_id):
        evaluation = self._get_evaluation(evaluation_id, request.user)
        entries = request.data if isinstance(request.data, list) else request.data.get("entries", [])
        serializer = BulkGradeEntrySerializer(data=entries, many=True)
        serializer.is_valid(raise_exception=True)

        # Borne haute dépendante du barème de CETTE évaluation — vérifiée
        # ici (pas dans le serializer, générique et partagé avec la
        # grille multi-évaluations) et avant toute écriture, pour ne
        # jamais enregistrer une partie du lot puis rejeter le reste.
        for entry in serializer.validated_data:
            score = entry.get("score")
            if score is not None and not (0 <= score <= evaluation.max_score):
                raise ValidationError(
                    {"score": f"La note doit être comprise entre 0 et {evaluation.max_score}."}
                )

        valid_child_ids = set(
            Enrollment.objects.filter(
                school_class=evaluation.subject.school_class, status=EnrollmentStatus.ACTIVE
            ).values_list("child_id", flat=True)
        )
        saved = []
        for entry in serializer.validated_data:
            if entry["child"] not in valid_child_ids:
                continue  # élève qui n'est plus inscrit dans cette classe — ignoré, pas d'erreur bloquante
            grade = _save_grade(evaluation, entry["child"], entry.get("score"), entry.get("is_excused", False), request.user)
            saved.append(grade)
        return Response(GradeSerializer(saved, many=True).data)


class ClassTermsView(generics.ListAPIView):
    """Trimestres de l'établissement d'une classe — pour le sélecteur de
    trimestre de "Bulletins du trimestre". Un établissement peut n'avoir
    aucun trimestre marqué actif (MyActiveTermView renvoie alors 404) :
    le titulaire doit pouvoir choisir manuellement dans la liste
    complète plutôt que rester bloqué."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"),
            pk=self.kwargs["class_id"],
        )
        _require_class_view_access(school_class, self.request.user)
        establishment = school_class.track.department.establishment
        return Term.objects.filter(establishment=establishment)


class SubjectTermsView(generics.ListAPIView):
    """Trimestres de l'établissement de cette matière — pour le
    sélecteur de trimestre du tableur de notes. Distinct de
    TermListCreateView (réservée au directeur) : l'enseignant dédié n'a
    pas de DirectorProfile, il ne peut donc pas lister les trimestres par
    ce biais."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer
    pagination_class = None

    def get_queryset(self):
        subject = get_object_or_404(
            Subject.objects.select_related("school_class__track__department__establishment"),
            pk=self.kwargs["subject_id"],
        )
        _require_subject_teacher(subject, self.request.user)
        establishment = subject.school_class.track.department.establishment
        return Term.objects.filter(establishment=establishment)


class SubjectGradeGridView(APIView):
    """Tableur de notes complet d'une matière pour un trimestre — élèves
    actifs en lignes, TOUTES les évaluations du trimestre en colonnes, en
    une seule requête. Distinct d'EvaluationGradesView (une seule colonne
    à la fois) : réutilise sa logique de récupération d'effectif
    (services.active_enrollments) plutôt que de la dupliquer, ne calcule
    ni ne touche jamais la moyenne générale, Subject.coefficient, ni le
    système de bulletin — uniquement la moyenne de CETTE matière."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_subject(self, subject_id, user):
        subject = get_object_or_404(Subject.objects.select_related("school_class"), pk=subject_id)
        _require_subject_teacher(subject, user)
        return subject

    def get(self, request, subject_id, term_id):
        subject = self._get_subject(subject_id, request.user)
        term = get_object_or_404(Term, pk=term_id)

        evaluations = list(Evaluation.objects.filter(subject=subject, term=term).order_by("date", "id"))
        enrollments = services.active_enrollments(subject.school_class)
        grades_by_key = {
            (g.evaluation_id, g.child_id): g
            for g in Grade.objects.filter(evaluation__in=evaluations)
        }
        appreciations_by_child = {
            a.child_id: a.comment
            for a in SubjectAppreciation.objects.filter(subject=subject, term=term)
        }

        students = []
        for enrollment in enrollments:
            child = enrollment.child
            grades = {}
            for evaluation in evaluations:
                grade = grades_by_key.get((evaluation.id, child.id))
                grades[str(evaluation.id)] = (
                    {
                        "score": grade.score,
                        "is_excused": grade.is_excused,
                        # Traçabilité minimale (Point 8) : qui a saisi/modifié
                        # en dernier — pertinent surtout après une réaffectation
                        # de matière en cours d'année, où l'enseignant qui
                        # consulte la grille n'est pas forcément l'auteur.
                        "updated_by_name": grade.updated_by.get_full_name() if grade.updated_by_id else None,
                        "updated_at": grade.graded_at.isoformat(),
                    }
                    if grade else None
                )
            students.append({
                "child_id": child.id,
                "first_name": child.first_name,
                "last_name": child.last_name,
                "avatar": (
                    request.build_absolute_uri(child.user.avatar.url)
                    if child.user_id and child.user.avatar else None
                ),
                "grades": grades,
                # Moyenne de CETTE matière uniquement — jamais pondérée
                # par Subject.coefficient, jamais la moyenne générale.
                "subject_average": services.compute_subject_average(child, subject, term),
                # Brouillon d'appréciation de matière — copié dans
                # SubjectReportEntry.teacher_comment à la génération du
                # bulletin, voir GenerateReportCardsView.
                "appreciation": appreciations_by_child.get(child.id, ""),
            })

        return Response({
            "subject": subject.id,
            "term": TermSerializer(term).data,
            "evaluations": EvaluationSerializer(evaluations, many=True).data,
            "students": students,
        })

    def post(self, request, subject_id, term_id):
        subject = self._get_subject(subject_id, request.user)
        term = get_object_or_404(Term, pk=term_id)

        entries = request.data if isinstance(request.data, list) else request.data.get("entries", [])
        serializer = BulkGradeEntrySerializer(data=entries, many=True)
        serializer.is_valid(raise_exception=True)

        evaluation_ids = {entry["evaluation"] for entry in serializer.validated_data if entry.get("evaluation")}
        evaluations_by_id = {
            e.id: e for e in Evaluation.objects.filter(subject=subject, term=term, id__in=evaluation_ids)
        }
        valid_child_ids = set(
            Enrollment.objects.filter(
                school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
            ).values_list("child_id", flat=True)
        )

        # Borne haute par évaluation, vérifiée intégralement AVANT toute
        # écriture — jamais enregistrer une partie du lot puis rejeter le
        # reste (chaque colonne peut avoir un barème différent).
        errors = []
        for entry in serializer.validated_data:
            evaluation = evaluations_by_id.get(entry.get("evaluation"))
            if not evaluation:
                continue
            score = entry.get("score")
            if score is not None and not (0 <= score <= evaluation.max_score):
                errors.append(
                    f"« {evaluation.title} » : la note doit être comprise entre 0 et {evaluation.max_score}."
                )
        if errors:
            raise ValidationError({"score": errors})

        saved = []
        touched_child_ids = set()
        for entry in serializer.validated_data:
            evaluation = evaluations_by_id.get(entry.get("evaluation"))
            if not evaluation:
                continue  # évaluation hors matière/trimestre — ignorée, pas d'erreur bloquante
            if entry["child"] not in valid_child_ids:
                continue  # élève qui n'est plus inscrit dans cette classe — ignoré
            grade = _save_grade(evaluation, entry["child"], entry.get("score"), entry.get("is_excused", False), request.user)
            saved.append(grade)
            touched_child_ids.add(entry["child"])

        touched_children = {c.id: c for c in Child.objects.filter(id__in=touched_child_ids)}
        updated_averages = {
            str(child_id): services.compute_subject_average(touched_children[child_id], subject, term)
            for child_id in touched_child_ids
        }

        return Response({
            "saved": GradeSerializer(saved, many=True).data,
            "updated_averages": updated_averages,
        })


class SubjectStudentAppreciationView(APIView):
    """Sauvegarde le brouillon d'appréciation de matière d'UN élève — un
    élève à la fois, pour le même geste de saisie que le tableur (tap sur
    le nom, saisie courte, sauvegarde). Distinct des notes elles-mêmes :
    n'écrit jamais dans Grade/Evaluation."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, subject_id, term_id, child_id):
        subject = get_object_or_404(Subject, pk=subject_id)
        _require_subject_teacher(subject, request.user)
        term = get_object_or_404(Term, pk=term_id)

        if not Enrollment.objects.filter(
            school_class=subject.school_class, child_id=child_id, status=EnrollmentStatus.ACTIVE
        ).exists():
            raise ValidationError({"child_id": "Cet élève n'est pas inscrit activement dans cette classe."})

        comment = (request.data.get("comment") or "").strip()
        appreciation, _ = SubjectAppreciation.objects.update_or_create(
            subject=subject, child_id=child_id, term=term, defaults={"comment": comment}
        )
        return Response({"child_id": child_id, "comment": appreciation.comment})


class ClassReportPreviewView(APIView):
    """Aperçu des moyennes calculées AVANT publication — pour que le
    directeur (ou le titulaire) vérifie que tout est cohérent avant de
    déclencher la génération définitive des bulletins. Rien n'est écrit
    en base ici, uniquement du calcul à la volée."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id, term_id):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
        )
        term = get_object_or_404(Term, pk=term_id)
        _require_class_manage_access(school_class, request.user)

        result = services.compute_class_rankings(school_class, term)
        return Response({
            "class_average": result["class_average"],
            "ranked": [
                {
                    "child": e["child"].id, "first_name": e["child"].first_name,
                    "last_name": e["child"].last_name, "general_average": e["general_average"],
                    "rank": e["rank"],
                    "avatar": (
                        request.build_absolute_uri(e["child"].user.avatar.url)
                        if e["child"].user_id and e["child"].user.avatar else None
                    ),
                }
                for e in result["ranked"]
            ],
            "without_average": [
                {"child": c.id, "first_name": c.first_name, "last_name": c.last_name}
                for c in result["without_average"]
            ],
        })


class GenerateReportCardsView(APIView):
    """Génération ET publication des bulletins de TOUTE une classe pour un
    trimestre, en un seul geste — jamais élève par élève. Le titulaire de
    la classe valide et déclenche cette génération pour SA classe ; le
    directeur conserve la capacité de le faire aussi, en supervision,
    mais n'est plus le seul chemin possible (même principe que le passage
    de classe en masse). Republier écrase le bulletin précédent du même
    trimestre (utile si une erreur de note est corrigée après une 1re
    publication, AVANT republication — un bulletin déjà consulté sans
    republication explicite reste figé)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, class_id, term_id):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
        )
        term = get_object_or_404(Term, pk=term_id)
        _require_class_manage_access(school_class, request.user)

        homeroom_comments = request.data.get("homeroom_comments", {})  # {child_id: "commentaire"}
        # Décisions du conseil de classe saisies par le titulaire — toutes
        # optionnelles, jamais bloquantes : un trimestre sans absence ni
        # sanction à signaler reste un {} vide côté frontend.
        absences = request.data.get("absences", {})  # {child_id: {"justified": x, "unjustified": y}}
        distinctions = request.data.get("distinctions", {})  # {child_id: "honor_roll" | ...}
        sanctions = request.data.get("sanctions", {})  # {child_id: "work_warning" | ...}
        result = services.compute_class_rankings(school_class, term)
        subjects = list(Subject.objects.filter(school_class=school_class))
        # Brouillons d'appréciation de matière saisis depuis le tableur —
        # copiés dans l'entrée figée, jamais recalculés après publication.
        appreciations_by_key = {
            (a.subject_id, a.child_id): a.comment
            for a in SubjectAppreciation.objects.filter(subject__in=subjects, term=term)
        }

        created_or_updated = []
        for entry in result["ranked"]:
            child = entry["child"]
            child_key = str(child.id)
            absence_entry = absences.get(child_key) or {}
            # Une distinction explicitement choisie par le titulaire prime ;
            # sinon, suggestion automatique à partir de la moyenne — jamais
            # "Refusé(e)", qui reste une décision humaine (voir
            # services.suggest_distinction).
            distinction = distinctions.get(child_key) or services.suggest_distinction(entry["general_average"])
            # Traçabilité minimale (Point 8) : `created_by` n'est jamais
            # réécrit une fois posé — seule `defaults` d'un update_or_create
            # s'appliquerait aussi bien à la création qu'à une
            # republication, ce qui perdrait l'auteur de la 1re publication.
            report_card, is_new = ReportCard.objects.update_or_create(
                child=child, term=term,
                defaults={
                    "school_class": school_class,
                    "general_average": entry["general_average"],
                    "class_average": result["class_average"],
                    "highest_average": result["highest_average"],
                    "lowest_average": result["lowest_average"],
                    "rank": entry["rank"],
                    "class_size": entry["class_size"],
                    "homeroom_comment": homeroom_comments.get(child_key, ""),
                    "justified_absence_hours": absence_entry.get("justified") or 0,
                    "unjustified_absence_hours": absence_entry.get("unjustified") or 0,
                    "distinction": distinction,
                    "sanction": sanctions.get(child_key) or ReportCardSanction.NONE,
                    "updated_by": request.user,
                },
            )
            if is_new:
                report_card.created_by = request.user
                report_card.save(update_fields=["created_by"])
            report_card.subject_entries.all().delete()
            for subject in subjects:
                subject_avg = services.compute_subject_average(child, subject, term)
                teacher_name = (
                    f"{subject.teacher.first_name} {subject.teacher.last_name}".strip()
                    if subject.teacher_id
                    else ""
                )
                SubjectReportEntry.objects.create(
                    report_card=report_card, subject_name=subject.name,
                    subject_average=subject_avg, coefficient=subject.coefficient,
                    teacher_comment=appreciations_by_key.get((subject.id, child.id), ""),
                    teacher_name=teacher_name, category=subject.category,
                )

            from .pdf import generate_and_attach_report_card

            generate_and_attach_report_card(report_card)
            created_or_updated.append(report_card)

            if child.user_id:
                notify_user(
                    child.user, NotificationType.REPORT_CARD_PUBLISHED,
                    title="Bulletin disponible",
                    body=f"Votre bulletin du {term} est disponible, moyenne générale : {entry['general_average']}/20.",
                )
            if child.parent and child.parent.user_id:
                notify_user(
                    child.parent.user, NotificationType.REPORT_CARD_PUBLISHED,
                    title="Bulletin disponible",
                    body=f"Le bulletin de {child.first_name} pour le {term} est disponible.",
                )

        return Response(
            ReportCardSerializer(created_or_updated, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyReportCardsView(generics.ListAPIView):
    """Bulletins publiés de l'élève connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportCardSerializer
    pagination_class = None

    def get_queryset(self):
        child = getattr(self.request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        return ReportCard.objects.filter(child=child).prefetch_related("subject_entries")


class MyGradesView(APIView):
    """Notes chiffrées de l'élève connecté, groupées par matière puis par
    trimestre, avec la moyenne de matière déjà calculée pour chaque
    trimestre — en LECTURE SEULE, jamais modifiable côté élève.

    Volontairement indépendant de ReportCard/bulletin publié : un élève
    doit pouvoir consulter ses notes dès qu'elles sont saisies, sans
    attendre qu'un enseignant génère et publie le bulletin du trimestre
    (qui reste un document figé distinct, consulté depuis "Bulletins").
    C'est aussi cette même moyenne "en direct" qui alimente le radar de
    compétences du tableau de bord — voir get_my_subject_averages."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        return Response(services.my_grades_for_child(child))


class MyGradesPdfView(APIView):
    """Export PDF, à la demande, des notes chiffrées de l'élève connecté —
    mêmes données que MyGradesView (services.my_grades_for_child), mise en
    forme imprimable. Jamais persisté sur disque contrairement au bulletin
    (ReportCard.document) : les notes évoluent en continu au fil du
    trimestre, un fichier généré une fois serait obsolète dès la note
    suivante saisie — régénéré à chaque appel, coût négligeable."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        from .pdf import render_my_grades_pdf

        pdf_bytes = render_my_grades_pdf(child, services.my_grades_for_child(child))
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="mes_resultats_{child.id}.pdf"'
        return response


@method_decorator(xframe_options_exempt, name="get")
class ReportCardPdfView(APIView):
    """Bulletin en PDF, régénéré à la demande à partir des données déjà
    figées du ReportCard (moyennes, rangs, appréciations... jamais
    recalculées) — jamais servi depuis le fichier stocké
    (ReportCard.document), qui dépend du disque/S3 et peut devenir
    introuvable après coup (redéploiement, stockage local éphémère,
    objet supprimé...). Cette source — le ReportCard en base — est
    toujours disponible, donc cet endpoint ne peut jamais renvoyer un
    404 "fichier manquant" comme le faisait le lien direct vers le
    fichier. Accessible à l'élève, son parent, le titulaire ou tout
    enseignant dédié de la classe, et le directeur (voir
    _require_report_card_view_access)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, report_card_id):
        report_card = get_object_or_404(
            ReportCard.objects.select_related(
                "child", "child__parent", "child__user", "term",
                "school_class__track__department__establishment",
            ).prefetch_related("subject_entries"),
            pk=report_card_id,
        )
        _require_report_card_view_access(report_card, request.user)
        from .pdf import render_report_card_pdf

        pdf_bytes = render_report_card_pdf(report_card)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = (
            f'{disposition}; filename="bulletin_{report_card.child_id}_{report_card.term_id}.pdf"'
        )
        return response


class ClassReportCardsView(generics.ListAPIView):
    """Bulletins déjà publiés d'une classe pour un trimestre — consultés
    par le titulaire, un enseignant dédié d'une matière de cette classe,
    ou le directeur (voir _require_report_card_view_access). Distinct de
    ClassReportPreviewView (aperçu de calcul AVANT publication) : ici on
    ne lit que des bulletins déjà figés."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportCardSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"), pk=self.kwargs["class_id"]
        )
        term = get_object_or_404(Term, pk=self.kwargs["term_id"])
        _require_class_view_access(school_class, self.request.user)
        return (
            ReportCard.objects.filter(school_class=school_class, term=term)
            .select_related("child")
            .prefetch_related("subject_entries")
            .order_by("rank")
        )


class ChildReportCardsView(generics.ListAPIView):
    """Bulletins publiés d'un enfant, consultés par son parent."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportCardSerializer
    pagination_class = None

    def get_queryset(self):
        child = get_object_or_404(Child, pk=self.kwargs["child_id"])
        if not child.parent_id or child.parent.user_id != self.request.user.id:
            raise PermissionDenied("Cet élève n'est pas rattaché à votre compte.")
        return ReportCard.objects.filter(child=child).prefetch_related("subject_entries")


class JoinRequestCreateView(APIView):
    """Soumission d'une demande de rattachement à un établissement —
    utilisée juste après l'inscription (flux normal) ou plus tard depuis
    l'écran "Rejoindre mon établissement" (option "plus tard" honorée).
    Jamais une inscription automatique : crée une demande PENDING, le
    directeur valide ensuite."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        if EstablishmentJoinRequest.objects.filter(child=child, status=JoinRequestStatus.PENDING).exists():
            return Response(
                {"detail": "Une demande est déjà en attente pour ce compte."}, status=status.HTTP_400_BAD_REQUEST
            )

        establishment_id = request.data.get("establishment")
        other_name = (request.data.get("other_establishment_name") or "").strip()
        declared_level = request.data.get("declared_level", child.class_level)

        if not establishment_id and not other_name:
            raise ValidationError({"establishment": "Précisez un établissement, ou son nom si absent de la liste."})

        establishment = None
        if establishment_id:
            from apps.users.models import DirectorProfile

            # La recherche d'établissement (EstablishmentDirectoryCardSerializer)
            # renvoie l'ID UTILISATEUR, pas DirectorProfile.pk (distincts,
            # DirectorProfile.user n'est pas la clé primaire) — cohérent
            # avec la route publique /auth/establishments/<user_id>/.
            establishment = get_object_or_404(DirectorProfile, user_id=establishment_id)

        join_request = EstablishmentJoinRequest.objects.create(
            child=child, establishment=establishment,
            other_establishment_name="" if establishment else other_name,
            declared_level=declared_level,
        )

        if establishment:
            notify_user(
                establishment.user, NotificationType.ENROLLMENT_UPDATE,
                title="Nouvelle demande de rattachement",
                body=f"{child.first_name} {child.last_name} demande à rejoindre votre établissement.",
                data={"join_request_id": join_request.id},
            )

        return Response(JoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)


class MyJoinRequestView(APIView):
    """Statut de la demande de rattachement de l'élève connecté."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        join_request = EstablishmentJoinRequest.objects.filter(child=child).order_by("-created_at").first()
        return Response({
            "join_request": JoinRequestSerializer(join_request).data if join_request else None,
        })


class DirectorJoinRequestsView(generics.ListAPIView):
    """Demandes de rattachement en attente pour l'établissement du
    directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JoinRequestSerializer
    pagination_class = None

    def get_queryset(self):
        establishment = _require_join_request_access(self.request.user)
        return EstablishmentJoinRequest.objects.filter(
            establishment=establishment
        ).select_related("child").order_by("status", "-created_at")


class ReviewJoinRequestView(APIView):
    """Le directeur valide ou rejette une demande — jamais d'écriture
    automatique en base avant ce geste humain. L'approbation peut inclure
    directement le placement en classe (class_id) : un seul geste plutôt
    que deux allers-retours, essentiel quand l'effectif est important."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        establishment = _require_join_request_access(request.user)
        join_request = get_object_or_404(
            EstablishmentJoinRequest.objects.select_related("child__user"), pk=pk, establishment=establishment
        )
        if join_request.status != JoinRequestStatus.PENDING:
            return Response({"detail": "Cette demande a déjà été traitée."}, status=status.HTTP_400_BAD_REQUEST)

        approve = request.data.get("approve", True)
        join_request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.REJECTED
        join_request.rejection_reason = request.data.get("rejection_reason", "") if not approve else ""
        join_request.reviewed_at = timezone.now()
        join_request.save(update_fields=["status", "rejection_reason", "reviewed_at"])

        enrollment_created = False
        class_id = request.data.get("class_id")
        if approve and class_id:
            from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass

            school_class = get_object_or_404(
                SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
            )
            if school_class.track.department.establishment_id != establishment.id:
                raise ValidationError({"class_id": "Cette classe n'appartient pas à votre établissement."})
            _, enrollment_created = Enrollment.objects.get_or_create(
                child=join_request.child, school_class=school_class,
                defaults={"status": EnrollmentStatus.ACTIVE},
            )

        if join_request.child.user_id:
            body = (
                f"{establishment.school_name} a approuvé votre rattachement."
                if approve
                else f"{establishment.school_name} a refusé votre rattachement"
                f"{' : ' + join_request.rejection_reason if join_request.rejection_reason else '.'}"
            )
            if enrollment_created:
                body += f" Vous êtes inscrit(e) en {school_class}."
            notify_user(
                join_request.child.user, NotificationType.ENROLLMENT_UPDATE,
                title="Rattachement " + ("approuvé" if approve else "refusé"),
                body=body,
            )
        return Response(JoinRequestSerializer(join_request).data)


class ApprovedUnplacedChildrenView(generics.ListAPIView):
    """Élèves dont la demande de rattachement a été approuvée mais qui ne
    sont encore inscrits dans aucune classe — le pont naturel entre
    l'admission et l'affectation à une classe, pour éviter au directeur
    de rechercher un par un les élèves auto-inscrits (Child.parent nul,
    donc introuvables par email de parent)."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        establishment = _require_join_request_access(request.user)
        approved = EstablishmentJoinRequest.objects.filter(
            establishment=establishment, status=JoinRequestStatus.APPROVED
        ).select_related("child")

        unplaced = []
        for join_request in approved:
            has_active_enrollment = Enrollment.objects.filter(
                child=join_request.child, status=EnrollmentStatus.ACTIVE
            ).exists()
            if not has_active_enrollment:
                unplaced.append({
                    "child": join_request.child.id,
                    "first_name": join_request.child.first_name,
                    "last_name": join_request.child.last_name,
                    "declared_level": join_request.declared_level,
                    "approved_at": join_request.reviewed_at,
                })
        return Response(unplaced)


class ParseAdmissionReportView(APIView):
    """Dépôt d'un rapport d'admission (CSV ou PDF) — parse le fichier et
    propose un rapprochement avec les demandes de rattachement en
    attente. Rien n'est écrit en base ici : c'est une proposition à
    relire, voir ConfirmAdmissionReportView pour l'application réelle."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        establishment = _require_join_request_access(request.user)
        uploaded = request.FILES.get("file")
        if not uploaded:
            raise ValidationError({"file": "Un fichier est requis."})

        from . import admission_report

        filename = (uploaded.name or "").lower()
        if filename.endswith(".csv"):
            try:
                extracted = admission_report.parse_csv_report(uploaded)
            except Exception:
                raise ValidationError({"file": "Fichier CSV illisible — vérifiez l'encodage et les colonnes."})
        elif filename.endswith(".pdf"):
            try:
                extracted = admission_report.parse_pdf_report(uploaded)
            except Exception:
                raise ValidationError({"file": "Fichier PDF illisible."})
        else:
            raise ValidationError({"file": "Formats acceptés : .csv ou .pdf."})

        pending = EstablishmentJoinRequest.objects.filter(
            establishment=establishment, status=JoinRequestStatus.PENDING
        ).select_related("child")
        proposals = admission_report.match_report_to_join_requests(extracted, pending)
        return Response({"total_lines": len(extracted), "proposals": proposals})


class ConfirmAdmissionReportView(APIView):
    """Application du rapprochement — après relecture du directeur.
    Traite chaque ligne indépendamment (un échec n'annule jamais les
    autres), même principe que le passage en masse."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        establishment = _require_join_request_access(request.user)
        decisions = request.data.get("decisions", [])
        if not isinstance(decisions, list) or not decisions:
            raise ValidationError({"decisions": "Au moins une décision est requise."})

        results = []
        for decision in decisions:
            join_request_id = decision.get("join_request_id")
            approve = decision.get("approve", True)
            class_id = decision.get("class_id")
            try:
                join_request = EstablishmentJoinRequest.objects.select_related("child__user").get(
                    pk=join_request_id, establishment=establishment, status=JoinRequestStatus.PENDING
                )
                join_request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.REJECTED
                join_request.reviewed_at = timezone.now()
                join_request.save(update_fields=["status", "reviewed_at"])

                if approve and class_id:
                    from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass

                    school_class = SchoolClass.objects.select_related(
                        "track__department__establishment"
                    ).get(pk=class_id)
                    if school_class.track.department.establishment_id != establishment.id:
                        raise ValueError("Classe hors établissement.")
                    Enrollment.objects.get_or_create(
                        child=join_request.child, school_class=school_class,
                        defaults={"status": EnrollmentStatus.ACTIVE},
                    )

                if join_request.child.user_id:
                    notify_user(
                        join_request.child.user, NotificationType.ENROLLMENT_UPDATE,
                        title="Rattachement " + ("approuvé" if approve else "refusé"),
                        body=f"{establishment.school_name} a traité votre demande suite au rapport d'admission.",
                    )
                results.append({"join_request_id": join_request_id, "success": True})
            except (EstablishmentJoinRequest.DoesNotExist, ValueError) as exc:
                results.append({"join_request_id": join_request_id, "success": False, "error": str(exc)})

        return Response({
            "processed": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
        })


class ClassesForJoinRequestPlacementView(generics.ListAPIView):
    """Classes de l'établissement pour placer un élève lors du traitement
    d'une demande de rattachement (approbation directe ou rapport
    d'admission) — accessible au directeur ou à l'enseignant délégué pour
    les rattachements (voir _require_join_request_access), jamais pour la
    gestion des classes elle-même (création/modification), qui reste
    strictement director-only via apps.academics.SchoolClassViewSet."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_serializer_class(self):
        from apps.academics.serializers import SchoolClassSerializer

        return SchoolClassSerializer

    def get_queryset(self):
        establishment = _require_join_request_access(self.request.user)
        return SchoolClass.objects.filter(
            track__department__establishment=establishment
        ).select_related("track", "homeroom_teacher")
