from django.core.management.base import BaseCommand

from governance.policy import ensure_default_rules
from governance.seed import ensure_default_roles


class Command(BaseCommand):
    help = 'Install/refresh default sub-admin roles and policy rules (idempotent).'

    def handle(self, *args, **opts):
        n = ensure_default_roles()
        ensure_default_rules()
        self.stdout.write(self.style.SUCCESS(f'{n} default roles ensured.'))
