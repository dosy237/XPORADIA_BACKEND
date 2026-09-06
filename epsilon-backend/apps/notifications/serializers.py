from rest_framework import serializers

from .models import DevicePlatform, Notification, NotificationCategory


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


class NotificationPreferenceEntrySerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=NotificationCategory.choices)
    category_label = serializers.CharField()
    enabled = serializers.BooleanField()


class UpdateNotificationPreferenceSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=NotificationCategory.choices)
    enabled = serializers.BooleanField()
