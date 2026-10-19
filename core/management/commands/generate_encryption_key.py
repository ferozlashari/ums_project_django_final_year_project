from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a new Fernet key for FIELD_ENCRYPTION_KEY and print it."

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode('utf-8')
        self.stdout.write(self.style.SUCCESS('Add this line to your .env file:'))
        self.stdout.write(f'FIELD_ENCRYPTION_KEY={key}')
