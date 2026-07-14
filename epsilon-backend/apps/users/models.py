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

    # Visibilité & préférences (E-14 — Paramètres du compte)
    profile_visible = models.BooleanField(
        default=True, verbose_name="Profil public visible"
    )
    notify_email = models.BooleanField(default=True, verbose_name="Notifications par email")
    notify_sms = models.BooleanField(default=False, verbose_name="Notifications par SMS")
    notify_push = models.BooleanField(default=True, verbose_name="Notifications push")

    # RGPD — droit à l'effacement : on anonymise plutôt que de supprimer la
    # ligne, pour préserver l'intégrité référentielle des certifications,
    # recrutements et autres historiques légaux qui pointent vers ce compte.
    deletion_requested_at = models.DateTimeField(null=True, blank=True)

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


def _generate_code():
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class PreRegistrationCode(models.Model):
    """Code remis à un enseignant ayant suivi et validé une formation en
    présentiel Xporadia, avant même de créer son compte sur la plateforme.

    Un enseignant ne devient "officiellement" enseignant Xporadia (habilité à
    être recommandé, à apparaître dans l'annuaire, à proposer des cours
    particuliers ou à postuler) qu'après avoir renseigné ce code et qu'un
    administrateur l'ait validé — c'est ce qui garantit la crédibilité de
    l'accréditation Xporadia : personne ne peut sauter les étapes.
    """

    code = models.CharField(max_length=12, unique=True, default=_generate_code)
    label = models.CharField(
        max_length=255, blank=True, verbose_name="Session de formation (ex : Cocody, mars 2026)"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="preregistration_codes_created"
    )
    used_by = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="preregistration_code_used"
    )
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Code de préinscription"
        verbose_name_plural = "Codes de préinscription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ({'utilisé' if self.is_used else 'disponible'})"


class TeacherProfile(models.Model):
    """PROFIL_ENSEIGNANT — étend User quand primary_role = teacher."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="teacher_profile"
    )
    preregistration_code = models.OneToOneField(
        PreRegistrationCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="teacher_profile"
    )
    subjects = models.JSONField(default=list, blank=True, verbose_name="Matières enseignées")
    experience_years = models.PositiveSmallIntegerField(default=0, verbose_name="Années d'expérience")
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Tarif horaire (FCFA)"
    )
    location = models.CharField(max_length=255, blank=True, verbose_name="Localisation")
    bio = models.TextField(blank=True, verbose_name="Bio professionnelle")
    identity_document = models.FileField(
        upload_to="identity_docs/", null=True, blank=True, verbose_name="Carte d'identité"
    )
    available_for_tutoring = models.BooleanField(default=False, verbose_name="Disponible cours particuliers")
    available_for_employment = models.BooleanField(default=True, verbose_name="Disponible marché de l'emploi")

    class Meta:
        verbose_name = "Profil enseignant"
        verbose_name_plural = "Profils enseignants"

    def __str__(self):
        return f"Profil enseignant — {self.user.get_full_name()}"


class TeacherDiploma(models.Model):
    """Diplôme uploadé par l'enseignant à l'inscription."""

    teacher = models.ForeignKey(
        TeacherProfile, on_delete=models.CASCADE, related_name="diplomas"
    )
    title = models.CharField(max_length=255, verbose_name="Intitulé du diplôme")
    file = models.FileField(upload_to="diplomas/", verbose_name="Fichier (PDF/image)")
    obtained_year = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Diplôme"
        verbose_name_plural = "Diplômes"

    def __str__(self):
        return f"{self.title} — {self.teacher.user.get_full_name()}"


class DirectorProfile(models.Model):
    """PROFIL_DIRECTEUR — étend User quand primary_role = director."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="director_profile"
    )
    school_name = models.CharField(max_length=255, verbose_name="Nom de l'école")
    address = models.CharField(max_length=255, verbose_name="Adresse")
    levels_taught = models.JSONField(default=list, blank=True, verbose_name="Niveaux enseignés")
    legal_documents = models.FileField(
        upload_to="school_docs/", null=True, blank=True, verbose_name="Documents légaux"
    )
    student_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="Effectif")
    is_partner = models.BooleanField(default=False, verbose_name="École Partenaire Epsilon")

    class Meta:
        verbose_name = "Profil directeur"
        verbose_name_plural = "Profils directeurs"

    def __str__(self):
        return f"{self.school_name} — {self.user.get_full_name()}"


class CompanyProfile(models.Model):
    """PROFIL_ENTREPRISE — étend User quand primary_role = company.

    Ajouté à l'EP-01 : l'épique mentionnait déjà l'entreprise parmi les rôles
    différenciés, mais aucune US ni entité MCD ne la détaillait. Modèle
    validé avec le Product Owner, même structure que PROFIL_DIRECTEUR.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="company_profile"
    )
    company_name = models.CharField(max_length=255, verbose_name="Raison sociale")
    sector = models.CharField(max_length=255, blank=True, verbose_name="Secteur d'activité")
    address = models.CharField(max_length=255, verbose_name="Adresse")
    legal_documents = models.FileField(
        upload_to="company_docs/", null=True, blank=True, verbose_name="Documents légaux"
    )
    is_partner = models.BooleanField(default=False, verbose_name="Entreprise partenaire premium")

    class Meta:
        verbose_name = "Profil entreprise"
        verbose_name_plural = "Profils entreprises"

    def __str__(self):
        return f"{self.company_name} — {self.user.get_full_name()}"


class ParentProfile(models.Model):
    """PROFIL_PARENT — étend User quand primary_role = parent."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="parent_profile"
    )
    location = models.CharField(max_length=255, blank=True, verbose_name="Localisation")
    subscription_active = models.BooleanField(default=False, verbose_name="Abonnement actif")

    class Meta:
        verbose_name = "Profil parent"
        verbose_name_plural = "Profils parents"

    def __str__(self):
        return f"Profil parent — {self.user.get_full_name()}"


class Child(models.Model):
    """ENFANT — rattaché à un ParentProfile (1 parent possède 0..N enfants)."""

    parent = models.ForeignKey(
        ParentProfile, on_delete=models.CASCADE, related_name="children"
    )
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    class_level = models.CharField(max_length=50, verbose_name="Classe")
    target_subjects = models.JSONField(default=list, blank=True, verbose_name="Matières cibles")

    class Meta:
        verbose_name = "Enfant"
        verbose_name_plural = "Enfants"

    def __str__(self):
        return f"{self.first_name} ({self.class_level})"


class OTPPurpose(models.TextChoices):
    ACCOUNT_VERIFICATION = "account_verification", "Vérification de compte"
    PASSWORD_RESET = "password_reset", "Réinitialisation mot de passe"


class OTPCode(models.Model):
    """Code de vérification à usage unique (email — simulateur SMS en dev)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_codes")
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=30, choices=OTPPurpose.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Code OTP"
        verbose_name_plural = "Codes OTP"
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        from django.utils import timezone
        return not self.used and self.expires_at > timezone.now()

    def __str__(self):
        return f"OTP {self.code} — {self.user.email} ({self.purpose})"
