from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    # Both spellings: a POST redirected by APPEND_SLASH would lose its body.
    path("process-video", views.process_video, name="process-video"),
    path("process-video/", views.process_video, name="process-video-slash"),
]
