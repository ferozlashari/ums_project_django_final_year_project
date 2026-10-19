import core.upload_validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hostel', '0002_hostel_gender_docs'),
    ]

    operations = [
        migrations.AlterField(
            model_name='hostelapplication',
            name='cnic_copy',
            field=models.FileField(blank=True, default='', help_text='Scanned copy of CNIC/B-Form (PDF/JPG/PNG, max 5MB).', upload_to='hostel_docs/cnic/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
        migrations.AlterField(
            model_name='hostelapplication',
            name='guardian_consent_letter',
            field=models.FileField(blank=True, help_text='Signed guardian consent letter (required for undergraduate applicants).', null=True, upload_to='hostel_docs/consent/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
        migrations.AlterField(
            model_name='hostelapplication',
            name='medical_certificate',
            field=models.FileField(blank=True, help_text='Recent medical fitness certificate, if your campus requires one.', null=True, upload_to='hostel_docs/medical/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
    ]
