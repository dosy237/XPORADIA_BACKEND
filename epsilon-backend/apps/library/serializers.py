from rest_framework import serializers

from apps.users.models import UserRole

from .models import LibraryResource


class LibraryResourceSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = LibraryResource
        fields = [
            "id", "title", "description", "resource_type", "level", "subject",
            "file_url", "file_size_kb", "tags", "author_name", "is_contributed",
            "download_count", "avg_rating", "is_archived", "is_favorited", "can_manage", "created_at",
        ]
        read_only_fields = [
            "id", "author_name", "is_contributed", "download_count",
            "avg_rating", "is_favorited", "can_manage", "created_at",
        ]

    def get_author_name(self, obj):
        return obj.author.get_full_name() if obj.author else "Xporadia"

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.favorited_by.filter(user=request.user).exists()

    def get_can_manage(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        if obj.author_id == user.id:
            return True
        return user.has_role(UserRole.DIRECTOR) and obj.establishment.user_id == user.id


class AffiliatedEstablishmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    school_name = serializers.CharField()
