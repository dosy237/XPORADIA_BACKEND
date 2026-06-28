
# ============================================================
# apps/virtual_classes/models.py
# ============================================================
 
import uuid
from django.conf import settings
from django.db import models
 
 
class VirtualClass(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="virtual_classes",
                                     limit_choices_to={"primary_role": "teacher"})
    name        = models.CharField(max_length=200)
    subject     = models.CharField(max_length=50)
    level       = models.CharField(max_length=50)
    description = models.TextField(max_length=500, blank=True)
    invite_code = models.CharField(max_length=10, unique=True)
    is_active   = models.BooleanField(default=True)
    members     = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                          through="ClassMember",
                                          related_name="joined_classes",
                                          blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Classe virtuelle"
        verbose_name_plural = "Classes virtuelles"
        ordering            = ["-created_at"]
 
    def __str__(self):
        return f"{self.name} — {self.teacher.get_full_name()}"
 
 
class MemberRole(models.TextChoices):
    STUDENT = "student", "Élève"
    PARENT  = "parent",  "Parent (lecture)"
 
 
class ClassMember(models.Model):
    virtual_class = models.ForeignKey(VirtualClass, on_delete=models.CASCADE)
    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role          = models.CharField(max_length=10, choices=MemberRole.choices,
                                      default=MemberRole.STUDENT)
    joined_at     = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ("virtual_class", "user")
        verbose_name    = "Membre de classe"
 
    def __str__(self):
        return f"{self.user.get_full_name()} → {self.virtual_class.name} [{self.role}]"
 
 
class ExerciseStatus(models.TextChoices):
    DRAFT     = "draft",     "Brouillon"
    PUBLISHED = "published", "Publié"
    CLOSED    = "closed",    "Clôturé"
 
 
class Exercise(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    virtual_class = models.ForeignKey(VirtualClass, on_delete=models.CASCADE,
                                       related_name="exercises")
    title         = models.CharField(max_length=200)
    instructions  = models.TextField()
    attachments   = models.JSONField(default=list)
    deadline      = models.DateTimeField(null=True, blank=True)
    status        = models.CharField(max_length=15, choices=ExerciseStatus.choices,
                                      default=ExerciseStatus.DRAFT)
    published_at  = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Exercice"
        verbose_name_plural = "Exercices"
        ordering            = ["-created_at"]
 
    def __str__(self):
        return f"{self.title} — {self.virtual_class.name}"
 
 
class AppreciationLevel(models.TextChoices):
    EXCELLENT = "excellent", "Très bien"
    GOOD      = "good",      "Bien"
    TO_REVIEW = "to_review", "À revoir"
    FAIL      = "fail",      "Insuffisant"
 
 
class SubmissionStatus(models.TextChoices):
    SUBMITTED = "submitted", "Soumis"
    GRADED    = "graded",    "Corrigé"
 
 
class Submission(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exercise     = models.ForeignKey(Exercise, on_delete=models.CASCADE,
                                      related_name="submissions")
    student      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="submissions")
    content      = models.TextField(blank=True)
    file_url     = models.URLField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    grade        = models.DecimalField(max_digits=4, decimal_places=2,
                                        null=True, blank=True)
    appreciation = models.CharField(max_length=15, choices=AppreciationLevel.choices,
                                     blank=True)
    feedback     = models.TextField(blank=True)
    annotations  = models.JSONField(default=list)
    status       = models.CharField(max_length=15, choices=SubmissionStatus.choices,
                                     default=SubmissionStatus.SUBMITTED)
    graded_at    = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        verbose_name        = "Soumission"
        verbose_name_plural = "Soumissions"
        unique_together     = ("exercise", "student")
        ordering            = ["submitted_at"]
 
    def __str__(self):
        return f"{self.student.get_full_name()} → {self.exercise.title}"
 
 
class MessageScope(models.TextChoices):
    CLASS    = "class",    "Canal général"
    EXERCISE = "exercise", "Fil exercice"
    PRIVATE  = "private",  "Message privé"
 
 
class ClassMessage(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    virtual_class = models.ForeignKey(VirtualClass, on_delete=models.CASCADE,
                                       related_name="messages")
    sender        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                       related_name="class_messages")
    scope         = models.CharField(max_length=10, choices=MessageScope.choices,
                                      default=MessageScope.CLASS)
    exercise      = models.ForeignKey(Exercise, on_delete=models.SET_NULL,
                                       null=True, blank=True,
                                       related_name="discussion_messages")
    recipient     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True,
                                       related_name="received_class_messages")
    body          = models.TextField()
    attachments   = models.JSONField(default=list)
    is_deleted    = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Message de classe"
        verbose_name_plural = "Messages de classe"
        ordering            = ["created_at"]
 
    def __str__(self):
        return f"[{self.scope}] {self.sender.get_full_name()} → {self.virtual_class.name}"
 
 