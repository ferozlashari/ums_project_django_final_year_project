import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from cryptography.fernet import Fernet, InvalidToken
from registration.models import Student

class Command(BaseCommand):
    help = 'Re-encrypt Student.cnic values from an old Fernet key to the configured new FIELD_ENCRYPTION_KEY.'
    def add_arguments(self, parser):
        parser.add_argument('--old-key', default=os.environ.get('OLD_FIELD_ENCRYPTION_KEY',''))
        parser.add_argument('--new-key', default=os.environ.get('FIELD_ENCRYPTION_KEY',''))
        parser.add_argument('--dry-run', action='store_true')
    def handle(self, *args, **opts):
        old_key, new_key = opts['old_key'], opts['new_key']
        if not old_key or not new_key: raise CommandError('Provide --old-key and --new-key (or OLD_FIELD_ENCRYPTION_KEY/FIELD_ENCRYPTION_KEY).')
        try: old = Fernet(old_key.encode() if isinstance(old_key,str) else old_key); new = Fernet(new_key.encode() if isinstance(new_key,str) else new_key)
        except Exception as exc: raise CommandError(f'Invalid Fernet key: {exc}')
        converted=0; failed=[]
        with transaction.atomic():
            for student in Student.objects.only('id','admission_no','cnic'):
                raw = student.__class__.objects.filter(pk=student.pk).values_list('cnic', flat=True).first()
                if not raw: continue
                try:
                    plain = old.decrypt(raw.encode()).decode() if str(raw).startswith('gAAAAA') else str(raw)
                except InvalidToken:
                    failed.append(student.admission_no); continue
                if not opts['dry_run']:
                    # Bypass the model's current key and write ciphertext produced by the new key.
                    type(student).objects.filter(pk=student.pk).update(cnic=new.encrypt(plain.encode()).decode())
                converted += 1
        self.stdout.write(self.style.SUCCESS(f'Converted {converted} record(s). Failed: {len(failed)}.'))
        if failed:
            self.stdout.write(self.style.WARNING('Could not decrypt: ' + ', '.join(failed[:50])))
