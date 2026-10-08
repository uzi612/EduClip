"""MongoEngine connection bootstrap for request/worker processes (BACKEND-03).

Tests connect mongomock themselves; this is a no-op when a default
connection already exists. Raises RuntimeError when no Atlas URI is
configured (surfaced as 503 by the API layer).
"""


def ensure_mongoengine():
    try:
        from mongoengine.connection import get_connection

        get_connection()
        return
    except Exception:
        pass
    from django.conf import settings

    uri = getattr(settings, "MONGODB_ATLAS_URI", "") or ""
    if not uri:
        raise RuntimeError("MONGODB_ATLAS_URI is not configured.")
    import mongoengine as me

    me.connect(db=getattr(settings, "MONGODB_DB_NAME", "educlip"), host=uri)
