"""
Xporadia — apps/feed/models.py
Entités : Post, PostLike, PostComment

Fil d'actualité public : tout utilisateur au compte vérifié peut publier une
actualité depuis son profil (annonce, actualité pédagogique, offre visible,
retour d'expérience...). Contrairement aux annuaires (users/models.py), ce
n'est pas un annuaire de fiches mais un flux chronologique — plus proche du
fonctionnement d'un réseau professionnel que d'un catalogue.
"""
from django.conf import settings
from django.db import models


class PostVisibility(models.TextChoices):
    PUBLIC = "public", "Visible par tous (y compris visiteurs non connectés)"
    MEMBERS = "members", "Visible par les membres connectés uniquement"


class Post(models.Model):
    """Publication d'un utilisateur sur le fil d'actualité."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts"
    )
    title = models.CharField(max_length=150, blank=True, verbose_name="Titre")
    body = models.TextField(max_length=2000, verbose_name="Contenu")
    # Une publication porte soit des photos (PostImage, plusieurs), soit une
    # vidéo courte (une seule, 60s max — validé côté app à la sélection ET
    # ici en garde-fou), jamais les deux à la fois.
    video = models.FileField(upload_to="posts/videos/", null=True, blank=True)
    video_duration_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    # Extraits automatiquement du corps à l'enregistrement (#mot) — permet
    # de parcourir/filtrer par thème sans re-parser le texte à chaque
    # affichage. Voir Post.save().
    hashtags = models.JSONField(default=list, blank=True)
    visibility = models.CharField(
        max_length=20, choices=PostVisibility.choices, default=PostVisibility.PUBLIC
    )

    # Modération légère — les publications restent visibles tant qu'un
    # administrateur ne les masque pas explicitement (signalement traité).
    is_hidden = models.BooleanField(default=False, verbose_name="Masquée par modération")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Publication"
        verbose_name_plural = "Publications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at", "is_hidden"])]

    def save(self, *args, **kwargs):
        import re

        self.hashtags = sorted(set(re.findall(r"#(\w+)", self.body, flags=re.UNICODE)))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.author.get_full_name()} : {self.body[:50]}"


class PostImage(models.Model):
    """Une publication peut porter plusieurs photos, affichées en
    carrousel côté app — voir Post.video pour l'alternative vidéo."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="posts/")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Image de publication"
        verbose_name_plural = "Images de publication"
        ordering = ["order", "id"]

    def __str__(self):
        return f"Image {self.order} de {self.post_id}"


class PostLike(models.Model):
    """J'aime sur une publication — un utilisateur ne peut aimer qu'une fois."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_likes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "J'aime"
        verbose_name_plural = "J'aime"
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="unique_post_like_per_user")
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} aime « {self.post.body[:30]} »"


class Follow(models.Model):
    """Relation d'abonnement entre deux utilisateurs — celui qui suit est
    notifié des nouvelles publications de celui qu'il suit. C'est ce qui
    transforme le fil d'actualité en réseau plutôt qu'en simple flux."""

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following"
    )
    followed = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followers"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"
        constraints = [
            models.UniqueConstraint(fields=["follower", "followed"], name="unique_follow_pair"),
            models.CheckConstraint(check=~models.Q(follower=models.F("followed")), name="cannot_follow_self"),
        ]

    def __str__(self):
        return f"{self.follower.get_full_name()} suit {self.followed.get_full_name()}"


class PostComment(models.Model):
    """Commentaire sur une publication du fil d'actualité."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_comments"
    )
    body = models.TextField(max_length=1000, verbose_name="Commentaire")
    is_hidden = models.BooleanField(default=False, verbose_name="Masqué par modération")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Commentaire de publication"
        verbose_name_plural = "Commentaires de publication"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author.get_full_name()} → « {self.post.body[:30]} »"
