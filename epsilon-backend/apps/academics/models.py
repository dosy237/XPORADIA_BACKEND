"""
Xporadia — apps/academics/models.py

Structure académique d'un établissement (privé, du primaire au supérieur) :
Département → Filière → Classe → Matière, avec un enseignant titulaire par
classe et un enseignant dédié par matière.

Stories 1, 2 et 5 du chantier "Classes" (structure, matières, effectifs).
Le contenu pédagogique (Story 3) et la bibliothèque (Story 4) vivent dans
d'autres apps ; l'espace élève (Story 6) est construit — voir apps.users
(Child.user, StudentActivationInvite) et apps.messaging.
"""
import secrets

from django.conf import settings
from django.db import models

from apps.users.models import Child, DirectorProfile


class DelegatedTask(models.TextChoices):
    """Tâches que le directeur peut confier à un enseignant de confiance,
    à l'échelle de TOUT l'établissement — pas une par classe/filière comme
    Department.track_delegates ou Track.class_delegates, qui restent
    scopées à un objet précis. Pense "censeur" dans une école réelle :
    souvent un enseignant ordinaire, chargé en plus de la gestion des
    emplois du temps pour toute l'école, sans que ça en fasse un rôle de
    compte à part — juste une capacité en plus, révocable à tout moment.
    Cette liste est volontairement extensible : d'autres tâches
    (surveillance, discipline, etc.) pourront s'y ajouter sans toucher au
    mécanisme lui-même."""

    TIMETABLE = "timetable", "Gestion des emplois du temps"


class TaskDelegation(models.Model):
    establishment = models.ForeignKey(DirectorProfile, on_delete=models.CASCADE, related_name="task_delegations")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_delegations_received"
    )
    task = models.CharField(max_length=20, choices=DelegatedTask.choices)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Délégation de tâche"
        verbose_name_plural = "Délégations de tâches"
        unique_together = ("establishment", "teacher", "task")

    def __str__(self):
        return f"{self.teacher.get_full_name()} — {self.get_task_display()} ({self.establishment.school_name})"


class Department(models.Model):
    """Département d'un établissement — ex: "Primaire", "Secondaire",
    "Sciences et Technologies". Le découpage est libre : un établissement
    primaire peut n'avoir qu'un seul département générique."""

    establishment = models.ForeignKey(
        DirectorProfile, on_delete=models.CASCADE, related_name="departments"
    )
    name = models.CharField(max_length=200, verbose_name="Nom du département")
    description = models.TextField(blank=True)
    # La création d'un DÉPARTEMENT reste exclusivement du ressort du
    # directeur, jamais délégable — seule la création des FILIÈRES en
    # dessous peut être confiée à un enseignant de confiance.
    track_delegates = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="delegated_departments",
        verbose_name="Enseignants autorisés à créer des filières ici",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        unique_together = ("establishment", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.establishment.school_name}"


class Track(models.Model):
    """Filière au sein d'un département — ex: "Scientifique", "Littéraire",
    "Génie Informatique". Pour un établissement sans filières distinctes
    (primaire), une seule filière générique suffit."""

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=200, verbose_name="Nom de la filière")
    description = models.TextField(blank=True)
    # Symétrique à Department.track_delegates, un niveau plus bas — délègue
    # la création des CLASSES de cette filière.
    class_delegates = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="delegated_tracks",
        verbose_name="Enseignants autorisés à créer des classes ici",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Filière"
        verbose_name_plural = "Filières"
        unique_together = ("department", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.department.name})"


class SchoolClass(models.Model):
    """Classe au sein d'une filière, pour une année scolaire donnée — ex:
    "Terminale D1", "CM2 A". L'enseignant titulaire est affecté par
    l'établissement et sera responsable de la classe (création des
    matières, réception des notes des enseignants dédiés — stories
    suivantes)."""

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=100, verbose_name="Nom de la classe")
    school_year = models.CharField(
        max_length=9, verbose_name="Année scolaire", help_text="Ex : 2025-2026"
    )
    homeroom_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homeroom_classes",
        limit_choices_to={"primary_role": "teacher"},
        verbose_name="Enseignant titulaire",
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Effectif maximum")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Classe"
        verbose_name_plural = "Classes"
        unique_together = ("track", "name", "school_year")
        ordering = ["-school_year", "name"]

    def __str__(self):
        return f"{self.name} — {self.school_year} ({self.track.name})"


class SubjectCategory(models.TextChoices):
    """Regroupement d'une matière pour les sous-totaux ("Bilan LETTRES",
    "Bilan SCIENCES", "Bilan AUTRES") du bulletin officiel — classé par
    l'enseignant titulaire de la classe (comme le reste de la gestion des
    matières), jamais par l'enseignant dédié à la matière ni le directeur.
    "Autres" par défaut pour toute matière non encore classée."""

    LETTERS = "letters", "Lettres"
    SCIENCES = "sciences", "Sciences"
    OTHER = "other", "Autres"


class Subject(models.Model):
    """Matière enseignée au sein d'une classe — ex: "Mathématiques",
    "Physique-Chimie". Créée par l'enseignant titulaire de la classe, qui
    y affecte un enseignant dédié (Story 2 du chantier "Classes"). Le
    contenu pédagogique (cours, exercices, corrections, notes — Story 3)
    se rattache à cette matière."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150, verbose_name="Nom de la matière")
    category = models.CharField(
        max_length=10, choices=SubjectCategory.choices, default=SubjectCategory.OTHER,
        verbose_name="Groupe (bulletin)",
    )
    # Poids de cette matière dans la moyenne générale de CETTE classe —
    # fixé par le directeur, jamais par l'enseignant lui-même (qui ne doit
    # pas pouvoir gonfler l'importance de sa propre matière). Une même
    # matière peut peser différemment d'une classe à l'autre (Terminale D
    # vs 6ème), d'où le rattachement au Subject plutôt qu'à un référentiel
    # global de matières.
    coefficient = models.PositiveSmallIntegerField(default=1, verbose_name="Coefficient")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dedicated_subjects",
        limit_choices_to={"primary_role": "teacher"},
        verbose_name="Enseignant dédié",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Matière"
        verbose_name_plural = "Matières"
        unique_together = ("school_class", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.school_class}"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Lundi"
    TUESDAY = 1, "Mardi"
    WEDNESDAY = 2, "Mercredi"
    THURSDAY = 3, "Jeudi"
    FRIDAY = 4, "Vendredi"
    SATURDAY = 5, "Samedi"


class TimetableSlot(models.Model):
    """Créneau d'emploi du temps — toute la classe partage le même
    planning (cohérent avec le fait qu'une Subject n'a qu'un seul
    enseignant dédié pour toute la classe). Alimente le rappel de révision
    envoyé la veille de chaque cours (voir apps.academics management
    command remind_timetable_revisions).

    `term` est nul par défaut : le créneau vaut alors pour toute l'année
    scolaire — ce qui ne veut jamais dire "tous les jours du calendrier",
    seulement les jours qui tombent dans un Term existant (voir
    apps.academics.services.term_for_date, qui déduit les vacances des
    trous entre trimestres plutôt que de les stocker séparément). Si
    `term` est renseigné, le créneau n'est actif que pendant ce trimestre
    précis (ex: option ne durant qu'un trimestre)."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="timetable_slots")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="timetable_slots")
    term = models.ForeignKey(
        "grading.Term", on_delete=models.SET_NULL, null=True, blank=True, related_name="timetable_slots",
        verbose_name="Trimestre (vide = toute l'année)",
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=50, blank=True, verbose_name="Salle")

    class Meta:
        verbose_name = "Créneau d'emploi du temps"
        verbose_name_plural = "Créneaux d'emploi du temps"
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.subject.name} — {self.get_weekday_display()} {self.start_time.strftime('%H:%M')}"


class WeekdayFull(models.IntegerChoices):
    """Comme Weekday, mais avec le dimanche — les cours officiels n'ont
    jamais lieu le dimanche (voir Weekday), mais un élève peut tout à fait
    vouloir y planifier un créneau personnel."""

    MONDAY = 0, "Lundi"
    TUESDAY = 1, "Mardi"
    WEDNESDAY = 2, "Mercredi"
    THURSDAY = 3, "Jeudi"
    FRIDAY = 4, "Vendredi"
    SATURDAY = 5, "Samedi"
    SUNDAY = 6, "Dimanche"


class PersonalScheduleBlock(models.Model):
    """Créneau personnel qu'un élève ajoute lui-même dans les parties
    vides de sa journée (hors cours officiels) — révision ou autre.
    Récurrent par défaut, avec un mécanisme d'exception au jour le jour
    exactement comme un événement récurrent d'agenda grand public (Google
    Calendar) :
      - modifier UNE occurrence précise crée une PersonalScheduleException
        liée à cette date, sans toucher à la règle qui continue normalement
        pour les autres dates ;
      - modifier "cette date et les suivantes" clôt cette règle
        (valid_until = veille de la date) et en ouvre une nouvelle à partir
        de cette date avec les nouvelles valeurs (voir
        apps.academics.views.PersonalScheduleBlockOccurrenceView)."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="personal_schedule_blocks")
    weekday = models.IntegerField(choices=WeekdayFull.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    title = models.CharField(max_length=200)
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Matière (optionnel)",
    )
    valid_from = models.DateField(verbose_name="Valide à partir du")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Valide jusqu'au (vide = indéfini)")

    class Meta:
        verbose_name = "Créneau personnel"
        verbose_name_plural = "Créneaux personnels"
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.title} — {self.get_weekday_display()} {self.start_time.strftime('%H:%M')}"


class PersonalScheduleException(models.Model):
    """Exception ponctuelle à un PersonalScheduleBlock pour une date
    précise — nouvel horaire/titre ce jour-là, ou annulation pure et
    simple — sans jamais modifier la règle récurrente elle-même."""

    block = models.ForeignKey(PersonalScheduleBlock, on_delete=models.CASCADE, related_name="exceptions")
    date = models.DateField()
    is_cancelled = models.BooleanField(default=False, verbose_name="Occurrence annulée")
    title = models.CharField(max_length=200, blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Exception de créneau personnel"
        verbose_name_plural = "Exceptions de créneau personnel"
        unique_together = ("block", "date")
        ordering = ["date"]

    def __str__(self):
        return f"Exception {self.date} — bloc {self.block_id}"


class TimetableReminderLog(models.Model):
    """Trace qu'un rappel des cours du lendemain a déjà été envoyé pour
    cette classe à cette date précise. TimetableSlot étant récurrent (pas
    une instance par date), l'idempotence ne peut pas reposer sur un champ
    horodaté directement sur le créneau comme pour Exercise
    (due_soon_notified_at) — on journalise donc par (classe, date)."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Journal de rappel d'emploi du temps"
        verbose_name_plural = "Journaux de rappel d'emploi du temps"
        unique_together = ("school_class", "date")


class PersonalBlockReminderLog(models.Model):
    """Même rôle que TimetableReminderLog, pour le rappel progressif de
    révision personnelle — PersonalScheduleBlock étant lui aussi récurrent,
    on journalise par (créneau, date)."""

    block = models.ForeignKey(PersonalScheduleBlock, on_delete=models.CASCADE, related_name="reminder_logs")
    date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Journal de rappel de révision personnelle"
        verbose_name_plural = "Journaux de rappel de révision personnelle"
        unique_together = ("block", "date")


class EventType(models.TextChoices):
    REPORT_CARD_DISTRIBUTION = "report_card_distribution", "Remise de bulletins"
    MEETING = "meeting", "Réunion"
    HOLIDAY = "holiday", "Jour férié"
    OTHER = "other", "Autre"


class EventAudience(models.TextChoices):
    STUDENTS = "students", "Élèves"
    PARENTS = "parents", "Parents"
    TEACHERS = "teachers", "Équipe enseignante"


class EstablishmentEvent(models.Model):
    """Événement ponctuel posé par un enseignant ou l'établissement — ni un
    cours officiel récurrent (TimetableSlot) ni un bloc personnel d'élève
    (PersonalScheduleBlock) : remise de bulletins, réunion, jour férié...
    `school_class` nul = concerne tout l'établissement. `audience` est une
    liste explicite de EventAudience — jamais déduite automatiquement du
    type, toujours fixée par le créateur (voir apps.academics.views,
    ClassEventListCreateView)."""

    establishment = models.ForeignKey(DirectorProfile, on_delete=models.CASCADE, related_name="events")
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, null=True, blank=True, related_name="events",
        verbose_name="Classe concernée (vide = tout l'établissement)",
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    audience = models.JSONField(default=list, verbose_name="Public cible")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Événement d'établissement"
        verbose_name_plural = "Événements d'établissement"
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.title} ({self.date})"


class TeacherInvitation(models.Model):
    """Invitation envoyée par email à un enseignant sans compte Xporadia
    encore actif, pour devenir l'enseignant dédié d'une Matière. Le lien
    contenu dans l'email amène la personne à créer son compte (ou à se
    connecter si elle en a déjà un) puis rattache automatiquement son
    compte à la matière une fois acceptée."""

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(verbose_name="Email invité")
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_teacher_invitations"
    )
    token = models.CharField(max_length=43, unique=True, editable=False)
    is_accepted = models.BooleanField(default=False)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Invitation enseignant"
        verbose_name_plural = "Invitations enseignant"
        unique_together = ("subject", "email")
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    def __str__(self):
        statut = "acceptée" if self.is_accepted else "en attente"
        return f"Invitation {self.email} → {self.subject} ({statut})"


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "active", "Inscrit"
    PROMOTED = "promoted", "Passé(e) en classe supérieure"
    REPEATING = "repeating", "Redouble"
    WITHDRAWN = "withdrawn", "Parti(e) de l'établissement"


class Enrollment(models.Model):
    """Inscription d'un élève (ENFANT) dans une classe, pour une année
    scolaire donnée — Story 5 du chantier "Classes". La mise à jour
    annuelle des effectifs (passage, redoublement, départ, nouvelle
    inscription) se fait en clôturant une inscription et, si l'élève
    continue dans l'établissement, en ouvrant la suivante dans la classe
    cible choisie par le directeur."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="enrollments")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=15, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE)
    # Régime et affectation ministérielle — mentions administratives du
    # bulletin officiel, souvent laissées vides même sur un vrai bulletin
    # papier (d'où `null=True` sur le régime : "non précisé" est une valeur
    # légitime, distincte d'"externe"). Pas d'écran de saisie dédié pour
    # l'instant (réglable via l'admin Django), au même titre que
    # Subject.category.
    is_boarder = models.BooleanField(null=True, blank=True, verbose_name="Interne (régime)")
    is_ministry_assigned = models.BooleanField(default=True, verbose_name="Affecté(e) par le ministère")
    enrolled_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        unique_together = ("child", "school_class")
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.child.first_name} — {self.school_class} ({self.status})"
