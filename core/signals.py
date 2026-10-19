from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    """Every User gets exactly one Profile, automatically, the moment the
    row is created - no matter which door they came in through (public
    /register/, Django admin's 'Add user', createsuperuser, the API, a
    management command). This is the single source of truth for role
    assignment; nothing else in the codebase should call Profile.objects.create()
    directly (use get_or_create/update_or_create so this signal can never
    cause a duplicate-row IntegrityError, the exact bug this replaces).

    The default role is strict and safe:
      - is_staff or is_superuser (checked or created via Django admin/
        createsuperuser)  -> 'admin'
      - everyone else                                          -> 'student'
    Anything more specific (faculty, staff, guardian) is set explicitly by
    whichever flow creates that kind of account (see core.views.register),
    which runs immediately after this signal and simply updates the role -
    it never conflicts with what the signal just created.
    """
    if not created:
        return
    from .models import Profile
    # Only a superuser starts as 'admin'; a staff-flag login starts as restricted 'staff'.
    role = 'admin' if instance.is_superuser else ('staff' if instance.is_staff else 'student')
    Profile.objects.get_or_create(user=instance, defaults={'role': role})
