"""
Xporadia — Modèle utilisateur personnalisé
Le modèle User est la fondation de toute la plateforme.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserRole(models.TextChoices):
    TEACHER = "teacher", "Enseignant"
    DIRECTOR = "director", "Directeur d'établissement"
    PARENT = "parent", "Parent d'élève"
    COMPANY = "company", "Entreprise"
    TRAINER = "trainer", "Formateur partenaire"
    ADMIN = "admin", "Administrateur Xporadia"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("primary_role", UserRole.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Utilisateur central Xporadia.
    Un utilisateur peut avoir plusieurs rôles (ex : Enseignant + Parent).
    Le primary_role est celui de l'inscription initiale.
    """
    # Identification
    email = models.EmailField(unique=True, verbose_name="Email")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")

    # Identité
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    last_name = models.CharField(max_length=100, verbose_name="Nom")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    # Rôles — multi-rôles supportés
    primary_role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        verbose_name="Rôle principal"
    )
    secondary_roles = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Rôles secondaires"
    )

    # Statuts
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False, verbose_name="Compte vérifié")
    is_documents_validated = models.BooleanField(
        default=False,
        verbose_name="Documents validés par Xporadia"
    )

    # Sécurité
    two_fa_enabled = models.BooleanField(default=False, verbose_name="2FA activée")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "primary_role"]

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}> [{self.primary_role}]"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_all_roles(self):
        roles = [self.primary_role]
        roles.extend(self.secondary_roles)
        return list(set(roles))

    def has_role(self, role: str) -> bool:
        return role in self.get_all_roles()
