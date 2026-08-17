"""
Xporadia — apps/messaging/models.py
Messagerie type Discord, scoping par classe/matière/DM/stage.

Quatre types de canal, chacun avec ses propres règles de création et
d'adhésion (voir apps/messaging/services.py pour la logique de peuplement
automatique) :
  - class       : un par SchoolClass, créé et administré par le titulaire.
  - subject     : créé à la discrétion de l'enseignant dédié d'une matière
                  (jamais automatique) — c'est ici que les devoirs sont
                  publiés.
  - direct      : messagerie privée 1:1, auto-créée entre un élève et
                  chaque enseignant dédié de ses matières.
  - internship  : ouvert à la signature complète d'une convention de
                  stage, archivé (pas supprimé) à la fin.
"""
from django.conf import settings
from django.db import models


class ChannelType(models.TextChoices):
    CLASS = "class", "Canal de classe"
    SUBJECT = "subject", "Canal de matière"
    DIRECT = "direct", "Message privé"
    INTERNSHIP = "internship", "Canal de stage"


class Channel(models.Model):
    channel_type = models.CharField(max_length=15, choices=ChannelType.choices)

    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.CASCADE, null=True, blank=True, related_name="channels"
    )
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.CASCADE, null=True, blank=True, related_name="channels"
    )
    internship_convention = models.OneToOneField(
        "internships.InternshipConvention", on_delete=models.CASCADE, null=True, blank=True,
        related_name="channel",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_archived = models.BooleanField(default=False, verbose_name="Archivé (lecture seule)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Canal"
        verbose_name_plural = "Canaux"
        ordering = ["-created_at"]
        constraints = [
            # Un seul canal de classe par classe, un seul canal par matière —
            # évite la prolifération de doublons que Xporadia veut justement
            # éviter (cf. besoin exprimé : "ne pas faire trop de groupes
            # pour une seule classe").
            models.UniqueConstraint(
                fields=["school_class"],
                condition=models.Q(channel_type=ChannelType.CLASS),
                name="one_class_channel_per_school_class",
            ),
            models.UniqueConstraint(
                fields=["subject"],
                condition=models.Q(channel_type=ChannelType.SUBJECT),
                name="one_channel_per_subject",
            ),
        ]

    def __str__(self):
        if self.channel_type == ChannelType.CLASS:
            return f"Classe — {self.school_class}"
        if self.channel_type == ChannelType.SUBJECT:
            return f"Matière — {self.subject}"
        if self.channel_type == ChannelType.INTERNSHIP:
            return f"Stage — {self.internship_convention}"
        members = ", ".join(m.user.get_full_name() for m in self.memberships.select_related("user")[:2])
        return f"Message privé — {members}"


class ChannelMembership(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_memberships"
    )
    is_admin = models.BooleanField(
        default=False, verbose_name="Administrateur du canal (titulaire / enseignant dédié)"
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Membre de canal"
        verbose_name_plural = "Membres de canal"
        unique_together = ("channel", "user")

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.channel}"


class Message(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent"
    )
    body = models.TextField(max_length=4000, blank=True)
    # Même convention que partout ailleurs (Exercise.attachments,
    # Submission.attachments) : liste de {"name", "url", "type"}.
    attachments = models.JSONField(default=list, blank=True)
    # Référence légère vers un devoir publié depuis ce message, sans
    # dupliquer la donnée — le devoir lui-même reste porté par Exercise
    # (virtual_classes). Permet d'afficher une carte "devoir" dans le fil
    # de discussion plutôt qu'un message texte brut.
    exercise_id = models.UUIDField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False, verbose_name="Épinglé")
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["channel", "created_at"])]

    def __str__(self):
        return f"{self.author.get_full_name()} — {self.body[:40]}"
