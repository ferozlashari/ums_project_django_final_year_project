import core.upload_validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0006_application_cnic_encrypted'),
    ]

    operations = [
        migrations.AlterField(
            model_name='application',
            name='cnic_copy',
            field=models.FileField(blank=True, default='', help_text='Scanned copy of CNIC/B-Form (PDF/JPG/PNG, max 5MB).', upload_to='admission_docs/cnic/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
        migrations.AlterField(
            model_name='application',
            name='education_certificate',
            field=models.FileField(blank=True, default='', help_text='Most recent degree/certificate (Matric/Inter/Bachelor as applicable).', upload_to='admission_docs/education/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
        migrations.AlterField(
            model_name='application',
            name='domicile_certificate',
            field=models.FileField(blank=True, help_text='Domicile certificate, if required by your program/quota.', null=True, upload_to='admission_docs/domicile/%Y/%m/', validators=[core.upload_validators.validate_document_upload]),
        ),
    ]
