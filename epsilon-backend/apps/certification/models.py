
# ============================================================
# apps/certification/models.py
# ============================================================
 
"""
Xporadia — apps/certification/models.py
"""
import uuid
from django.conf import settings
from django.db import models
 
 
class CertificationLevel(models.TextChoices):
    BRONZE = "bronze", "Bronze"
    SILVER = "silver", "Argent"
    GOLD   = "gold",   "Or"
 
 
class ModuleCategory(models.TextChoices):
    PEDAGOGY    = "pedagogy",    "Pédagogie générale"
    DIDACTICS   = "didactics",   "Didactique disciplinaire"
    MANAGEMENT  = "management",  "Gestion de classe"
    ETHICS      = "ethics",      "Éthique professionnelle"
    LEADERSHIP  = "leadership",  "Leadership pédagogique"
 
 
class TrainingModule(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title        = models.CharField(max_length=200)
    category     = models.CharField(max_length=30, choices=ModuleCategory.choices)
    description  = models.TextField()
    objectives   = models.JSONField(default=list)
    prerequisites = models.TextField(blank=True)
    duration_hours = models.PositiveSmallIntegerField(default=8)
    price        = models.PositiveIntegerField(help_text="FCFA")
    target_level = models.CharField(max_length=10, choices=CertificationLevel.choices,
                                     default=CertificationLevel.BRONZE)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Module de formation"
        verbose_name_plural = "Modules de formation"
        ordering            = ["category", "title"]
 
    def __str__(self):
        return f"{self.title} ({self.target_level})"
 
 
class SessionStatus(models.TextChoices):
    PLANNED   = "planned",   "Planifiée"
    ONGOING   = "ongoing",   "En cours"
    COMPLETED = "completed", "Terminée"
    CANCELLED = "cancelled", "Annulée"
 
 
class TrainingSession(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module        = models.ForeignKey(TrainingModule, on_delete=models.PROTECT,
                                       related_name="sessions")
    trainer       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                       related_name="trainer_sessions",
                                       limit_choices_to={"primary_role": "trainer"})
    city          = models.CharField(max_length=100)
    location      = models.CharField(max_length=300)
    date          = models.DateField()
    start_time    = models.TimeField()
    end_time      = models.TimeField()
    capacity      = models.PositiveSmallIntegerField(default=30)
    enrolled_count = models.PositiveSmallIntegerField(default=0)
    status        = models.CharField(max_length=15, choices=SessionStatus.choices,
                                      default=SessionStatus.PLANNED)
    enrollments   = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                            through="SessionEnrollment",
                                            related_name="enrolled_sessions",
                                            blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Session de formation"
        verbose_name_plural = "Sessions de formation"
        ordering            = ["-date"]
 
    def __str__(self):
        return f"{self.module.title} — {self.city} — {self.date}"
 
    @property
    def is_full(self):
        return self.enrolled_count >= self.capacity
 
    @property
    def places_left(self):
        return max(0, self.capacity - self.enrolled_count)
 
 
class SessionEnrollment(models.Model):
    session         = models.ForeignKey(TrainingSession, on_delete=models.CASCADE)
    teacher         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    enrolled_at     = models.DateTimeField(auto_now_add=True)
    payment_status  = models.CharField(max_length=20, default="pending",
                                        choices=[("pending","En attente"),
                                                 ("paid","Payé"),
                                                 ("refunded","Remboursé")])
    attendance_score = models.PositiveSmallIntegerField(null=True, blank=True)
 
    class Meta:
        unique_together = ("session", "teacher")
        verbose_name    = "Inscription session"
 
    def __str__(self):
        return f"{self.teacher} → {self.session}"
 
 
class QuestionType(models.TextChoices):
    MCQ  = "mcq",  "QCM"
    OPEN = "open", "Question ouverte"
    TF   = "tf",   "Vrai/Faux"
 
 
class DifficultyLevel(models.TextChoices):
    EASY   = "easy",   "Facile"
    MEDIUM = "medium", "Moyen"
    HARD   = "hard",   "Difficile"
 
 
class ExamQuestion(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module       = models.ForeignKey(TrainingModule, on_delete=models.CASCADE,
                                      related_name="questions")
    question_type = models.CharField(max_length=5, choices=QuestionType.choices)
    text         = models.TextField()
    options      = models.JSONField(default=list)
    correct_answer = models.CharField(max_length=500, blank=True)
    difficulty   = models.CharField(max_length=10, choices=DifficultyLevel.choices,
                                     default=DifficultyLevel.MEDIUM)
    points       = models.PositiveSmallIntegerField(default=1)
    times_used   = models.PositiveIntegerField(default=0)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Question d'examen"
        verbose_name_plural = "Questions d'examen"
        indexes             = [models.Index(fields=["module", "difficulty"])]
 
    def __str__(self):
        return f"[{self.module.title}] {self.text[:60]}..."
 
 
class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "En cours"
    SUBMITTED   = "submitted",   "Soumis"
    GRADED      = "graded",      "Noté"
    PASSED      = "passed",      "Réussi"
    FAILED      = "failed",      "Échoué"
 
 
class ExamAttempt(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                         related_name="exam_attempts")
    session         = models.ForeignKey(TrainingSession, on_delete=models.CASCADE,
                                         related_name="exam_attempts")
    is_retake       = models.BooleanField(default=False)
    answers         = models.JSONField(default=dict)
    score_auto      = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    score_manual    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    score_attendance = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    score_total     = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    trainer_feedback = models.TextField(blank=True)
    status          = models.CharField(max_length=15, choices=AttemptStatus.choices,
                                        default=AttemptStatus.IN_PROGRESS)
    started_at      = models.DateTimeField(auto_now_add=True)
    submitted_at    = models.DateTimeField(null=True, blank=True)
    graded_at       = models.DateTimeField(null=True, blank=True)
    graded_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, blank=True,
                                         related_name="graded_attempts")
 
    class Meta:
        verbose_name        = "Tentative d'examen"
        verbose_name_plural = "Tentatives d'examen"
        unique_together     = ("teacher", "session", "is_retake")
        ordering            = ["-started_at"]
 
    def __str__(self):
        t = "rattrapage" if self.is_retake else "principale"
        return f"Tentative {t} — {self.teacher} — {self.session}"
 
    def compute_total_score(self):
        if self.score_attendance is not None and self.score_auto is not None:
            manual = self.score_manual or 0
            exam_score = (self.score_auto + manual) / 2
            self.score_total = (self.score_attendance + exam_score) / 2
            self.save(update_fields=["score_total"])
        return self.score_total
 
 
class Certification(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="certifications")
    module       = models.ForeignKey(TrainingModule, on_delete=models.PROTECT,
                                      related_name="certifications")
    attempt      = models.OneToOneField(ExamAttempt, on_delete=models.PROTECT,
                                         related_name="certification")
    level        = models.CharField(max_length=10, choices=CertificationLevel.choices)
    score_total  = models.DecimalField(max_digits=5, decimal_places=2)
    qr_code      = models.CharField(max_length=100, unique=True)
    pdf_url      = models.URLField(blank=True)
    issued_at    = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateField()
    is_valid     = models.BooleanField(default=True)
    revoked_at   = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True)
 
    class Meta:
        verbose_name        = "Certification"
        verbose_name_plural = "Certifications"
        ordering            = ["-issued_at"]
        indexes             = [models.Index(fields=["qr_code"]),
                                models.Index(fields=["teacher", "is_valid"])]
 
    def __str__(self):
        return f"Certif {self.level} — {self.teacher} — {self.module.title}"
 
