from rest_framework import serializers

from apps.users.models import User


class PendingAccreditationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "avatar", "primary_role", "created_at"]
        read_only_fields = fields


class AdminUserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "avatar", "primary_role", "is_active", "created_at"]
        read_only_fields = fields
