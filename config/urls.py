"""Root URLconf (SETUP-01 + FRONTEND-01 landing)."""
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("watch/<str:video_id>/", TemplateView.as_view(template_name="watch.html"), name="watch"),
    path("api/v1/", include("apps.api_v1.urls")),
]

# Unmatched URLs return the JSON error envelope (BACKEND-06), not HTML.
handler404 = "apps.api_v1.exceptions.not_found_json"
