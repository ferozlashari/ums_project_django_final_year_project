from django.core.management.base import BaseCommand
from registration.models import Student
from core.encrypted_fields import is_decryption_unavailable

class Command(BaseCommand):
    help = 'Check encrypted student identity fields for values that cannot be decrypted with the configured key.'
    def handle(self, *args, **options):
        bad=[]; total=0
        for student in Student.objects.only('id','admission_no','cnic'):
            total += 1
            if is_decryption_unavailable(student.cnic): bad.append(student.admission_no)
        self.stdout.write(f'Checked {total} student record(s).')
        if bad:
            self.stdout.write(self.style.ERROR(f'Undecryptable records: {len(bad)}'))
            for admission_no in bad[:50]: self.stdout.write(f'  {admission_no}')
            self.stdout.write('The original encryption key is required to recover ciphertext; do not generate a replacement key and expect old values to decrypt.')
        else:
            self.stdout.write(self.style.SUCCESS('Encryption/decryption check passed.'))
