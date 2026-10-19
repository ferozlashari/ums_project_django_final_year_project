from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Registers the post_save signal that gives every User a Profile
        # automatically - whether the account was created through /register/,
        # Django admin's "Add user" screen, createsuperuser, or the API.
        # This is what makes role assignment "automatic" instead of relying
        # on every code path remembering to create a Profile by hand.
        import core.signals  # noqa: F401
        # Registers system checks (e.g. FIELD_ENCRYPTION_KEY configuration)
        # so `manage.py check` catches them at startup, not as a wall of
        # runtime warnings once someone opens a student record.
        import core.checks  # noqa: F401
