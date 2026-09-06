from django.contrib import admin

from .models import Post, PostComment, PostLike


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "body", "visibility", "is_hidden", "created_at"]
    list_filter = ["visibility", "is_hidden"]
    search_fields = ["body", "author__first_name", "author__last_name", "author__email"]


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ["id", "post", "author", "body", "is_hidden", "created_at"]
    list_filter = ["is_hidden"]
    search_fields = ["body", "author__first_name", "author__last_name"]


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ["id", "post", "user", "created_at"]
