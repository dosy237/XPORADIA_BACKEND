from datetime import timedelta

from django.db.models import Case, Count, F, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CommentLike, Follow, Post, PostComment, PostImage, PostLike, PostVisibility
from .realtime import broadcast_to_feed, broadcast_to_post
from .serializers import (
    CreatePostCommentSerializer,
    CreatePostSerializer,
    PostAuthorSerializer,
    PostCommentSerializer,
    PostSerializer,
)

MAX_IMAGES_PER_POST = 6

# Fenêtre de reclassement du fil "à la une" : au-delà, les publications
# repassent en ordre purement chronologique. Évite qu'une publication très
# commentée reste épinglée en tête indéfiniment — seule la fraîcheur récente
# profite du reclassement par activité.
FEED_RANKING_WINDOW_DAYS = 7
# Fenêtre d'observation de l'activité d'un auteur (publications, likes et
# commentaires donnés) utilisée pour estimer si son compte est "actif" —
# un compte actif voit son contenu récent mis en avant, conformément au
# principe demandé : plus on participe, plus on est vu.
AUTHOR_ACTIVITY_WINDOW_DAYS = 30


def _rank_for_feed(qs):
    """Classe le fil par activité (likes/commentaires du post + activité
    récente de l'auteur), dans une fenêtre récente, avec repli chronologique
    strict au-delà — un compromis simple et explicable plutôt qu'un vrai
    moteur de recommandation, cohérent avec la taille de la plateforme."""

    now = timezone.now()
    ranking_cutoff = now - timedelta(days=FEED_RANKING_WINDOW_DAYS)
    activity_since = now - timedelta(days=AUTHOR_ACTIVITY_WINDOW_DAYS)

    author_posts = (
        Post.objects.filter(author_id=OuterRef("author_id"), created_at__gte=activity_since)
        .order_by()
        .values("author_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    author_likes_given = (
        PostLike.objects.filter(user_id=OuterRef("author_id"), created_at__gte=activity_since)
        .order_by()
        .values("user_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    author_comments_given = (
        PostComment.objects.filter(author_id=OuterRef("author_id"), created_at__gte=activity_since)
        .order_by()
        .values("author_id")
        .annotate(c=Count("id"))
        .values("c")
    )

    return (
        qs.annotate(
            _like_count=Count("likes", distinct=True),
            _comment_count=Count("comments", distinct=True),
            _author_posts=Coalesce(Subquery(author_posts, output_field=IntegerField()), Value(0)),
            _author_likes_given=Coalesce(Subquery(author_likes_given, output_field=IntegerField()), Value(0)),
            _author_comments_given=Coalesce(
                Subquery(author_comments_given, output_field=IntegerField()), Value(0)
            ),
            _recent_bucket=Case(
                When(created_at__gte=ranking_cutoff, then=Value(1)), default=Value(0), output_field=IntegerField()
            ),
            _score=(
                F("_comment_count") * 3
                + F("_like_count") * 2
                + F("_author_posts")
                + F("_author_likes_given")
                + F("_author_comments_given")
            ),
        )
        .order_by("-_recent_bucket", "-_score", "-created_at")
    )


class IsVerifiedToPublish(permissions.BasePermission):
    """Un compte non vérifié (OTP jamais validé) ne peut pas publier ni
    commenter — évite les comptes jetables sur le fil public. Lecture
    toujours ouverte, gérée séparément par IsAuthenticatedOrReadOnly."""

    message = "Vérifiez votre compte (code reçu par email) avant de publier."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_verified)


class PostViewSet(viewsets.ModelViewSet):
    """Fil d'actualité — lecture publique (visiteurs inclus, hors
    publications réservées aux membres), publication réservée aux comptes
    vérifiés. Modification et suppression réservées à l'auteur (ou un
    administrateur)."""

    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsVerifiedToPublish]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            Post.objects.filter(is_hidden=False)
            .select_related("author")
            .prefetch_related("likes", "comments", "images")
        )
        if not (self.request.user and self.request.user.is_authenticated):
            qs = qs.filter(visibility=PostVisibility.PUBLIC)
        author_id = self.request.query_params.get("author")
        if author_id:
            qs = qs.filter(author_id=author_id)
        hashtag = self.request.query_params.get("hashtag")
        if hashtag:
            qs = qs.filter(hashtags__contains=[hashtag.lstrip("#")])
        query = self.request.query_params.get("q")
        if query:
            from django.db.models import Q

            qs = qs.filter(Q(title__icontains=query) | Q(body__icontains=query))
        if author_id:
            # Fil d'un profil précis : ordre chronologique attendu, pas de
            # reclassement par activité (voir _rank_for_feed).
            return qs.order_by("-created_at")
        return _rank_for_feed(qs)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return CreatePostSerializer
        return PostSerializer

    def update(self, request, *args, **kwargs):
        post = self.get_object()
        if post.author_id != request.user.id and not request.user.is_staff:
            return Response(
                {"detail": "Vous ne pouvez modifier que vos propres publications."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def _attach_my_following_ids(self, request):
        # Une seule requête pour tout le fil plutôt qu'une par auteur
        # affiché — voir PostAuthorSerializer.get_is_followed_by_me.
        if request.user.is_authenticated:
            request._my_following_ids = set(
                Follow.objects.filter(follower=request.user).values_list("followed_id", flat=True)
            )

    def list(self, request, *args, **kwargs):
        self._attach_my_following_ids(request)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        self._attach_my_following_ids(request)
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        post = serializer.instance

        # Photos multiples — envoyées sous la même clé "images" répétée en
        # multipart. Pas de dépendance à un ordre côté client : l'ordre
        # d'arrivée fait foi. La vidéo (optionnelle, exclusive des photos)
        # est un champ direct de Post, gérée par le serializer lui-même.
        images = request.FILES.getlist("images")
        if images and post.video:
            post.delete()
            raise ValidationError({"images": "Une publication porte soit des photos, soit une vidéo, pas les deux."})
        if len(images) > MAX_IMAGES_PER_POST:
            post.delete()
            raise ValidationError({"images": f"{MAX_IMAGES_PER_POST} photos maximum par publication."})
        PostImage.objects.bulk_create(
            [PostImage(post=post, image=image, order=i) for i, image in enumerate(images)]
        )

        self._attach_my_following_ids(request)
        post_data = PostSerializer(post, context={"request": request}).data
        self._notify_followers(post)
        broadcast_to_feed("post_created", {"post": post_data})
        return Response(post_data, status=status.HTTP_201_CREATED)

    def _notify_followers(self, post):
        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user

        preview = post.body[:80]
        for follow in Follow.objects.filter(followed=post.author).select_related("follower"):
            notify_user(
                follow.follower,
                NotificationType.FOLLOWED_USER_POST,
                title=f"{post.author.get_full_name()} a publié",
                body=preview,
                data={"post_id": post.id},
            )

    def destroy(self, request, *args, **kwargs):
        post = self.get_object()
        if post.author_id != request.user.id and not request.user.is_staff:
            return Response(
                {"detail": "Vous ne pouvez supprimer que vos propres publications."},
                status=status.HTTP_403_FORBIDDEN,
            )
        post_id = post.id
        response = super().destroy(request, *args, **kwargs)
        broadcast_to_feed("post_deleted", {"post_id": post_id})
        return response


class TogglePostLikeView(APIView):
    """Bascule le j'aime de l'utilisateur courant sur une publication."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, post_id):
        post = get_object_or_404(Post, pk=post_id, is_hidden=False)
        like, created = PostLike.objects.get_or_create(post=post, user=request.user)
        if not created:
            like.delete()
            liked = False
        else:
            liked = True
        like_count = post.likes.count()
        payload = {"post_id": post.id, "like_count": like_count}
        broadcast_to_feed("post_like_updated", payload)
        broadcast_to_post(post.id, "post_like_updated", payload)
        return Response({"liked": liked, "like_count": like_count})


class ToggleFollowView(APIView):
    """Bascule l'abonnement de l'utilisateur courant à un autre profil —
    c'est ce qui alimente la notification de nouvelle publication."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        from apps.users.models import User

        if request.user.id == int(user_id):
            raise ValidationError("Vous ne pouvez pas vous suivre vous-même.")
        followed = get_object_or_404(User, pk=user_id)
        follow, created = Follow.objects.get_or_create(follower=request.user, followed=followed)
        if not created:
            follow.delete()
            following = False
        else:
            following = True
        return Response({"following": following, "followers_count": followed.followers.count()})


class MyFollowingView(generics.ListAPIView):
    """Profils suivis par l'utilisateur connecté — alimente un futur onglet
    "Abonnements" du fil, ou un simple écran de gestion des abonnements."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PostAuthorSerializer
    pagination_class = None

    def get_queryset(self):
        from apps.users.models import User

        followed_ids = Follow.objects.filter(follower=self.request.user).values_list("followed_id", flat=True)
        return User.objects.filter(id__in=followed_ids)


class PostCommentListCreateView(generics.ListCreateAPIView):
    """Commentaires d'une publication donnée — /posts/<post_id>/comments/."""

    pagination_class = None
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsVerifiedToPublish]

    def get_post(self):
        try:
            return Post.objects.get(pk=self.kwargs["post_id"], is_hidden=False)
        except Post.DoesNotExist:
            raise Http404

    def get_queryset(self):
        return (
            PostComment.objects.filter(post=self.get_post(), is_hidden=False)
            .select_related("author")
            .prefetch_related("likes")
            .order_by("created_at")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreatePostCommentSerializer
        return PostCommentSerializer

    def perform_create(self, serializer):
        serializer.save(post=self.get_post(), author=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        comment = serializer.instance
        comment_data = PostCommentSerializer(comment, context={"request": request}).data
        broadcast_to_post(comment.post_id, "comment_created", {"comment": comment_data})
        broadcast_to_feed(
            "post_comment_count_updated",
            {"post_id": comment.post_id, "comment_count": comment.post.comments.count()},
        )
        return Response(comment_data, status=status.HTTP_201_CREATED)


class PostCommentDeleteView(generics.DestroyAPIView):
    """Suppression d'un commentaire — réservée à son auteur (aucune limite
    de temps, contrairement à certains réseaux) ou un administrateur."""

    permission_classes = [permissions.IsAuthenticated]
    queryset = PostComment.objects.all()

    def get_object(self):
        comment = get_object_or_404(PostComment, pk=self.kwargs["pk"], post_id=self.kwargs["post_id"])
        if comment.author_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("Vous ne pouvez supprimer que vos propres commentaires.")
        return comment

    def perform_destroy(self, instance):
        post_id = instance.post_id
        instance.delete()
        broadcast_to_post(post_id, "comment_deleted", {"comment_id": instance.id})
        broadcast_to_feed(
            "post_comment_count_updated",
            {"post_id": post_id, "comment_count": PostComment.objects.filter(post_id=post_id).count()},
        )


class ToggleCommentLikeView(APIView):
    """Bascule le j'aime de l'utilisateur courant sur un commentaire —
    diffusé sur le groupe du post pour que tous les clients qui consultent
    cette publication voient le compteur bouger en direct."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, post_id, pk):
        comment = get_object_or_404(PostComment, pk=pk, post_id=post_id, is_hidden=False)
        like, created = CommentLike.objects.get_or_create(comment=comment, user=request.user)
        if not created:
            like.delete()
            liked = False
        else:
            liked = True
        like_count = comment.likes.count()
        broadcast_to_post(
            post_id, "comment_like_updated", {"comment_id": comment.id, "like_count": like_count}
        )
        return Response({"liked": liked, "like_count": like_count})
