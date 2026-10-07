"""Root URLconf (SETUP-01)."""
from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.api_v1.urls")),
]
