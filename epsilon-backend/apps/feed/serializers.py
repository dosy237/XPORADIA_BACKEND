from rest_framework import serializers

from apps.users.models import User

from .models import Follow, Post, PostComment, PostImage, PostLike


class PostAuthorSerializer(serializers.ModelSerializer):
    """Identité minimale affichée sur une carte de publication — jamais
    l'email ni le téléphone, cohérent avec le reste des annuaires publics."""

    full_name = serializers.CharField(source="get_full_name", read_only=True)
    role_label = serializers.CharField(source="get_primary_role_display", read_only=True)
    is_followed_by_me = serializers.SerializerMethodField()
    followers_count = serializers.IntegerField(source="followers.count", read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "avatar", "primary_role", "role_label", "is_followed_by_me", "followers_count"]
        read_only_fields = fields

    def get_is_followed_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # `_prefetched_follower_ids` est injecté par PostViewSet pour éviter
        # une requête par auteur affiché sur un fil qui peut en compter des
        # dizaines — voir PostViewSet.get_queryset.
        prefetched = getattr(request, "_my_following_ids", None)
        if prefetched is not None:
            return obj.id in prefetched
        return Follow.objects.filter(follower=request.user, followed=obj).exists()


class PostCommentSerializer(serializers.ModelSerializer):
    author = PostAuthorSerializer(read_only=True)

    class Meta:
        model = PostComment
        fields = ["id", "post", "author", "body", "created_at"]
        read_only_fields = ["id", "post", "author", "created_at"]


class CreatePostCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostComment
        fields = ["body"]

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le commentaire ne peut pas être vide.")
        return value


class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ["id", "image", "order"]
        read_only_fields = ["id"]


class PostSerializer(serializers.ModelSerializer):
    author = PostAuthorSerializer(read_only=True)
    images = PostImageSerializer(many=True, read_only=True)
    like_count = serializers.IntegerField(source="likes.count", read_only=True)
    comment_count = serializers.IntegerField(source="comments.count", read_only=True)
    is_liked_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id", "author", "title", "body", "hashtags", "images", "visibility",
            "like_count", "comment_count", "is_liked_by_me", "created_at",
        ]
        read_only_fields = ["id", "author", "hashtags", "images", "created_at"]

    def get_is_liked_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # `likes` a été annoté/préchargé côté queryset (voir PostViewSet) —
        # éviter une requête N+1 par publication sur un fil qui peut compter
        # des dizaines d'entrées.
        return any(like.user_id == request.user.id for like in obj.likes.all())


class CreatePostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ["title", "body", "visibility"]

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("La publication ne peut pas être vide.")
        if len(value) > 2000:
            raise serializers.ValidationError("2000 caractères maximum.")
        return value
