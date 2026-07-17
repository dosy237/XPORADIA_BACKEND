from rest_framework import serializers

from .models import DevicePlatform, Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "notif_type", "channel", "title", "body", "data", "is_read", "read_at", "created_at"]
        read_only_fields = fields


class RegisterDeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=DevicePlatform.choices)


class UnregisterDeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
