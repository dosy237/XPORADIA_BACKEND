from django.urls import path

from . import views

urlpatterns = [
    path("posts/", views.PostViewSet.as_view({"get": "list", "post": "create"}), name="post-list"),
    path(
        "posts/<int:pk>/",
        views.PostViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="post-detail",
    ),
    path("posts/<int:post_id>/like/", views.TogglePostLikeView.as_view(), name="post-like-toggle"),
    path(
        "posts/<int:post_id>/comments/",
        views.PostCommentListCreateView.as_view(),
        name="post-comments",
    ),
    path("users/<int:user_id>/follow/", views.ToggleFollowView.as_view(), name="follow-toggle"),
    path("my-following/", views.MyFollowingView.as_view(), name="my-following"),
]
