"""EduClip Django config package."""
try:
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except ImportError:  # celery is optional for `manage.py check`
    __all__ = ()
