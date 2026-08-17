"""
Xporadia — apps/grading/models.py

Module "Vie scolaire" — trimestres, évaluations, notes, bulletins. Traité
comme un système de gestion scolaire à part entière, au même titre que la
messagerie : chaque établissement dispose de ce module dès sa création.

Principe directeur : les coefficients (matière, évaluation) sont fixés par
l'établissement (Subject.coefficient côté directeur, Evaluation.coefficient
côté enseignant pour pondérer SES propres évaluations dans SA matière),
jamais par un enseignant qui déciderait seul du poids de sa matière dans
la moyenne générale. Les moyennes sont recalculées à la volée tant qu'un
bulletin n'est pas publié ; à la publication, tout est figé (ReportCard),
pour ne jamais voir un bulletin déjà remis à une famille changer sous ses
yeux si une note est corrigée après coup.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.academics.models import Child, SchoolClass, Subject
from apps.users.models import DirectorProfile


class Term(models.Model):
    """Trimestre — le découpage temporel de toute note/moyenne/bulletin.
    Propre à un établissement et une année scolaire (pas un référentiel
    national partagé, chaque établissement définit ses propres dates)."""

    establishment = models.ForeignKey(DirectorProfile, on_delete=models.CASCADE, related_name="terms")
    school_year = models.CharField(max_length=9, verbose_name="Année scolaire", help_text="Ex. 2025-2026")
    number = models.PositiveSmallIntegerField(verbose_name="Numéro du trimestre")
    name = models.CharField(max_length=50, blank=True, verbose_name="Nom (optionnel)")
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True, verbose_name="Trimestre en cours")

    class Meta:
        verbose_name = "Trimestre"
        verbose_name_plural = "Trimestres"
        unique_together = ("establishment", "school_year", "number")
        ordering = ["-school_year", "-number"]

    def __str__(self):
        return self.name or f"Trimestre {self.number} ({self.school_year})"


class EvaluationType(models.TextChoices):
    HOMEWORK = "homework", "Devoir"
    QUIZ = "quiz", "Interrogation"
    EXAM = "exam", "Composition"


class Evaluation(models.Model):
    """Une évaluation notée — ex. \"Composition de maths, trimestre 1\".
    Le coefficient ici pondère UNIQUEMENT les évaluations entre elles au
    sein d'une même matière (une composition pèse plus qu'une
    interrogation) — différent de Subject.coefficient, qui pondère les
    matières entre elles dans la moyenne générale."""

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="evaluations")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="evaluations")
    title = models.CharField(max_length=200)
    eval_type = models.CharField(max_length=10, choices=EvaluationType.choices, default=EvaluationType.HOMEWORK)
    coefficient = models.PositiveSmallIntegerField(default=1)
    date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Évaluation"
        verbose_name_plural = "Évaluations"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.title} — {self.subject.name}"


class Grade(models.Model):
    """Note d'un élève à une évaluation, sur 20."""

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name="grades")
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="grades")
    score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    # Absence justifiée / dispense — la note est absente sans faire
    # baisser la moyenne (contrairement à une note de 0 bien réelle).
    is_excused = models.BooleanField(default=False)
    graded_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Note"
        verbose_name_plural = "Notes"
        unique_together = ("evaluation", "child")

    def __str__(self):
        return f"{self.child.first_name} — {self.evaluation.title} : {self.score if not self.is_excused else 'dispensé'}"


class ReportCard(models.Model):
    """Bulletin d'un élève pour un trimestre — figé à la publication
    (les moyennes ne sont jamais recalculées après coup pour un bulletin
    déjà publié, même si une note est corrigée ensuite)."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="report_cards")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="report_cards")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="report_cards")
    general_average = models.DecimalField(max_digits=4, decimal_places=2)
    class_average = models.DecimalField(max_digits=4, decimal_places=2)
    rank = models.PositiveSmallIntegerField()
    class_size = models.PositiveSmallIntegerField()
    homeroom_comment = models.TextField(blank=True, verbose_name="Appréciation du professeur principal")
    document = models.FileField(upload_to="report_cards/", null=True, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bulletin"
        verbose_name_plural = "Bulletins"
        unique_together = ("child", "term")
        ordering = ["-published_at"]

    def __str__(self):
        return f"Bulletin {self.child.first_name} — {self.term}"


class SubjectReportEntry(models.Model):
    """Détail par matière d'un bulletin — moyenne et coefficient figés à
    la publication, appréciation de l'enseignant de cette matière."""

    report_card = models.ForeignKey(ReportCard, on_delete=models.CASCADE, related_name="subject_entries")
    subject_name = models.CharField(max_length=150)
    subject_average = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    coefficient = models.PositiveSmallIntegerField()
    teacher_comment = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "Détail de matière du bulletin"
        verbose_name_plural = "Détails de matière du bulletin"

    def __str__(self):
        return f"{self.subject_name} — {self.subject_average}"


class JoinRequestStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    APPROVED = "approved", "Approuvée"
    REJECTED = "rejected", "Rejetée"


class EstablishmentJoinRequest(models.Model):
    """Demande de rattachement d'un élève à un établissement — jamais une
    inscription automatique. Créée soit à l'inscription du compte élève,
    soit plus tard depuis l'écran "Rejoindre mon établissement". Si
    l'établissement recherché n'est pas encore sur Xporadia, la demande
    reste en attente (establishment=None, other_establishment_name
    renseigné) jusqu'à ce qu'un directeur inscrive cet établissement et
    la retrouve lui-même."""

    # ForeignKey, pas OneToOne — un élève doit pouvoir refaire une demande
    # après un rejet, ou si sa 1re demande "Autre" reste bloquée en
    # attente qu'un établissement rejoigne Xporadia. La vue empêche
    # seulement d'avoir DEUX demandes PENDING simultanées, pas d'en avoir
    # plusieurs dans le temps.
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="join_requests")
    establishment = models.ForeignKey(
        DirectorProfile, on_delete=models.CASCADE, related_name="join_requests", null=True, blank=True
    )
    other_establishment_name = models.CharField(max_length=200, blank=True)
    declared_level = models.CharField(max_length=50, verbose_name="Niveau déclaré")
    status = models.CharField(max_length=10, choices=JoinRequestStatus.choices, default=JoinRequestStatus.PENDING)
    rejection_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Demande de rattachement"
        verbose_name_plural = "Demandes de rattachement"
        ordering = ["-created_at"]

    def __str__(self):
        target = self.establishment.school_name if self.establishment else self.other_establishment_name
        return f"{self.child.first_name} vers {target} ({self.status})"
