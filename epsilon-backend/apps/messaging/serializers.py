from django.utils import timezone
from rest_framework import serializers

from apps.users.models import User

from .models import Channel, ChannelMembership, ChannelType, Message


class ChannelMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    role_label = serializers.CharField(source="get_primary_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "avatar", "primary_role", "role_label"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    author = ChannelMemberSerializer(read_only=True)

    class Meta:
        model = Message
        fields = [
            "id", "channel", "author", "body", "attachments", "exercise_id",
            "is_pinned", "is_edited", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "channel", "author", "exercise_id", "is_edited", "created_at", "updated_at"]


class EditMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["body"]

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Le message ne peut pas être vide.")
        return value


class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["body", "attachments"]

    def validate(self, attrs):
        if not attrs.get("body", "").strip() and not attrs.get("attachments"):
            raise serializers.ValidationError("Un message ne peut pas être vide.")
        return attrs


class ChannelSerializer(serializers.ModelSerializer):
    """Carte de canal pour la liste — nom résolu selon le type, aperçu du
    dernier message, compteur de non-lus pour l'utilisateur courant."""

    display_name = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = [
            "id", "channel_type", "subject_id", "display_name", "subtitle", "avatar",
            "last_message", "unread_count", "is_archived", "created_at",
        ]
        read_only_fields = fields

    def get_display_name(self, obj):
        if obj.channel_type == ChannelType.CLASS:
            return str(obj.school_class)
        if obj.channel_type == ChannelType.SUBJECT:
            return obj.subject.name
        if obj.channel_type == ChannelType.INTERNSHIP:
            return f"Stage — {obj.internship_convention.application.offer.company.company_profile.company_name}"
        request = self.context.get("request")
        other = obj.memberships.exclude(user=request.user).select_related("user").first() if request else None
        return other.user.get_full_name() if other else "Message privé"

    def get_avatar(self, obj):
        # Seul un canal "direct" représente une vraie personne — un canal
        # de classe/matière/stage reste un groupe, sans avatar unique
        # pertinent (l'écran affiche une icône générique dans ce cas).
        if obj.channel_type != ChannelType.DIRECT:
            return None
        request = self.context.get("request")
        other = obj.memberships.exclude(user=request.user).select_related("user").first() if request else None
        if not other or not other.user.avatar:
            return None
        return request.build_absolute_uri(other.user.avatar.url) if request else other.user.avatar.url

    def get_subtitle(self, obj):
        if obj.channel_type == ChannelType.CLASS:
            return "Canal de classe"
        if obj.channel_type == ChannelType.SUBJECT:
            return obj.subject.school_class.name
        if obj.channel_type == ChannelType.INTERNSHIP:
            return "Canal de stage"
        request = self.context.get("request")
        other = obj.memberships.exclude(user=request.user).select_related("user").first() if request else None
        return other.user.get_primary_role_display() if other else ""

    def get_last_message(self, obj):
        last = obj.messages.order_by("-created_at").first()
        if not last:
            return None
        return {"body": last.body, "author_name": last.author.get_full_name(), "created_at": last.created_at}

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0
        membership = obj.memberships.filter(user=request.user).first()
        if not membership:
            return 0
        qs = obj.messages.exclude(author=request.user)
        if membership.last_read_at:
            qs = qs.filter(created_at__gt=membership.last_read_at)
        return qs.count()
