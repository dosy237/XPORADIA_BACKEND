
# ============================================================
# apps/users/models.py
# ============================================================
 
"""
Xporadia — apps/users/models.py
Entités : User, TeacherProfile, DirectorProfile, ParentProfile, Child
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
 
 
class UserRole(models.TextChoices):
    TEACHER  = "teacher",  "Enseignant"
    DIRECTOR = "director", "Directeur d'établissement"
    PARENT   = "parent",   "Parent d'élève"
    COMPANY  = "company",  "Entreprise"
    TRAINER  = "trainer",  "Formateur partenaire"
    ADMIN    = "admin",    "Administrateur Xporadia"
 
 
class SubjectChoice(models.TextChoices):
    MATHS     = "maths",     "Mathématiques"
    PHYSICS   = "physics",   "Physique-Chimie"
    SVT       = "svt",       "SVT"
    FRENCH    = "french",    "Français"
    HISTORY   = "history",   "Histoire-Géographie"
    ENGLISH   = "english",   "Anglais"
    PHILO     = "philo",     "Philosophie"
    ECONOMICS = "economics", "Économie"
    IT        = "it",        "Informatique"
    OTHER     = "other",     "Autre"
 
 
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire")
        email = self.normalize_email(email)
        user  = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
 
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("primary_role", UserRole.ADMIN)
        return self.create_user(email, password, **extra_fields)
 
 
class User(AbstractBaseUser, PermissionsMixin):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email         = models.EmailField(unique=True, verbose_name="Email")
    phone         = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    first_name    = models.CharField(max_length=100, verbose_name="Prénom")
    last_name     = models.CharField(max_length=100, verbose_name="Nom")
    avatar        = models.ImageField(upload_to="avatars/", blank=True, null=True)
    primary_role    = models.CharField(max_length=20, choices=UserRole.choices)
    secondary_roles = models.JSONField(default=list, blank=True)
    is_active              = models.BooleanField(default=True)
    is_staff               = models.BooleanField(default=False)
    is_verified            = models.BooleanField(default=False)
    is_documents_validated = models.BooleanField(default=False)
    two_fa_enabled         = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
 
    objects = UserManager()
    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "primary_role"]
 
    class Meta:
        verbose_name        = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering            = ["-created_at"]
        indexes             = [models.Index(fields=["email"]),
                                models.Index(fields=["primary_role"])]
 
    def __str__(self):
        return f"{self.get_full_name()} [{self.primary_role}]"
 
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
 
    def get_all_roles(self):
        return list(set([self.primary_role] + (self.secondary_roles or [])))
 
    def has_role(self, role: str) -> bool:
        return role in self.get_all_roles()
 
 
class TeacherProfile(models.Model):
    user              = models.OneToOneField(User, on_delete=models.CASCADE,
                                             related_name="teacher_profile")
    bio               = models.TextField(max_length=500, blank=True)
    subjects          = models.JSONField(default=list)
    levels            = models.JSONField(default=list)
    experience_years  = models.PositiveSmallIntegerField(default=0)
    diploma_files     = models.JSONField(default=list)
    available_for_job     = models.BooleanField(default=True)
    salary_expectation    = models.PositiveIntegerField(null=True, blank=True)
    available_for_tutoring = models.BooleanField(default=False)
    hourly_rate            = models.PositiveIntegerField(null=True, blank=True)
    tutoring_modes         = models.JSONField(default=list)
    radius_km              = models.PositiveSmallIntegerField(default=5)
    latitude               = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude              = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    avg_rating         = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews      = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Profil enseignant"
        verbose_name_plural = "Profils enseignants"
        indexes             = [models.Index(fields=["available_for_job"]),
                                models.Index(fields=["available_for_tutoring"])]
 
    def __str__(self):
        return f"Profil enseignant — {self.user.get_full_name()}"
 
 
class DirectorProfile(models.Model):
    user              = models.OneToOneField(User, on_delete=models.CASCADE,
                                             related_name="director_profile")
    school_name       = models.CharField(max_length=200)
    address           = models.TextField()
    city              = models.CharField(max_length=100)
    commune           = models.CharField(max_length=100, blank=True)
    student_count     = models.PositiveIntegerField(default=0)
    levels_taught     = models.JSONField(default=list)
    authorization_doc = models.FileField(upload_to="school_docs/", blank=True, null=True)
    rccm_number       = models.CharField(max_length=100, blank=True)
    is_partner        = models.BooleanField(default=False)
    partner_score     = models.PositiveSmallIntegerField(default=0)
    subscription_active  = models.BooleanField(default=False)
    subscription_end     = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Profil directeur"
        verbose_name_plural = "Profils directeurs"
 
    def __str__(self):
        return f"{self.school_name} — {self.user.get_full_name()}"
 
 
class ParentProfile(models.Model):
    user         = models.OneToOneField(User, on_delete=models.CASCADE,
                                         related_name="parent_profile")
    city         = models.CharField(max_length=100, blank=True)
    commune      = models.CharField(max_length=100, blank=True)
    latitude     = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude    = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    subscription_active = models.BooleanField(default=False)
 
    class Meta:
        verbose_name        = "Profil parent"
        verbose_name_plural = "Profils parents"
 
    def __str__(self):
        return f"Parent — {self.user.get_full_name()}"
 
 
class Child(models.Model):
    parent          = models.ForeignKey(ParentProfile, on_delete=models.CASCADE,
                                         related_name="children")
    first_name      = models.CharField(max_length=100)
    school_level    = models.CharField(max_length=50)
    target_subjects = models.JSONField(default=list)
 
    class Meta:
        verbose_name        = "Enfant"
        verbose_name_plural = "Enfants"
 
    def __str__(self):
        return f"{self.first_name} ({self.school_level})"
 