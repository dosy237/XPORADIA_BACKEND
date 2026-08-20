from django.urls import path

from . import views

urlpatterns = [
    path("my-establishments/", views.MyLibraryEstablishmentsView.as_view(), name="my-library-establishments"),
    path("my-favorites/", views.MyLibraryFavoritesView.as_view(), name="my-library-favorites"),
    path(
        "establishments/<int:establishment_id>/resources/",
        views.LibraryResourceListCreateView.as_view(),
        name="library-resource-list",
    ),
    path("resources/<uuid:pk>/", views.LibraryResourceDetailView.as_view(), name="library-resource-detail"),
    path(
        "resources/<uuid:pk>/download/",
        views.TrackResourceDownloadView.as_view(),
        name="library-resource-download",
    ),
    path(
        "resources/<uuid:pk>/favorite/",
        views.ToggleFavoriteView.as_view(),
        name="library-resource-favorite",
    ),
    path("resources/<uuid:pk>/rate/", views.RateResourceView.as_view(), name="library-resource-rate"),
]
