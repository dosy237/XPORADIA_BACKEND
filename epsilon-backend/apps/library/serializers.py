from rest_framework import serializers

from apps.users.models import UserRole

from .models import LibraryResource, ResourceRating


class LibraryResourceSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()

    class Meta:
        model = LibraryResource
        fields = [
            "id", "title", "description", "resource_type", "category", "level", "subject",
            "cover_image", "file_url", "pdf_file", "file_size_kb", "tags", "author_name",
            "is_contributed", "moderation_status", "download_count", "avg_rating", "ratings_count",
            "my_rating", "is_archived", "is_favorited", "can_manage", "created_at",
        ]
        read_only_fields = [
            "id", "author_name", "is_contributed", "moderation_status", "download_count",
            "avg_rating", "ratings_count", "my_rating", "is_favorited", "can_manage", "created_at",
        ]

    def validate(self, attrs):
        # PATCH ne renvoie que les champs modifiés — on ne vérifie
        # l'exclusivité qu'à la création, ou si l'un des deux champs est
        # explicitement touché par la mise à jour.
        is_create = self.instance is None
        touches_file = "file_url" in attrs or "pdf_file" in attrs
        if is_create or touches_file:
            file_url = attrs.get("file_url", getattr(self.instance, "file_url", ""))
            pdf_file = attrs.get("pdf_file", getattr(self.instance, "pdf_file", None))
            if not file_url and not pdf_file:
                raise serializers.ValidationError(
                    {"file_url": "Renseignez un PDF hébergé ou un lien externe."}
                )
            if file_url and pdf_file:
                raise serializers.ValidationError(
                    {"file_url": "Choisissez un PDF hébergé ou un lien externe, pas les deux."}
                )
        return attrs

    def get_author_name(self, obj):
        return obj.author.get_full_name() if obj.author else "Xporadia"

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.favorited_by.filter(user=request.user).exists()

    def get_my_rating(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        rating = obj.ratings.filter(user=request.user).first()
        return rating.score if rating else None

    def get_can_manage(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        if obj.author_id == user.id:
            return True
        return user.has_role(UserRole.DIRECTOR) and obj.establishment.user_id == user.id


class ResourceRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceRating
        fields = ["id", "score", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class AffiliatedEstablishmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    school_name = serializers.CharField()
