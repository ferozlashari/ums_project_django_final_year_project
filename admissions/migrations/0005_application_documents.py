from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0004_entrytest'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='cnic_copy',
            field=models.FileField(blank=True, default='', help_text='Scanned copy of CNIC/B-Form.', upload_to='admission_docs/cnic/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='application',
            name='education_certificate',
            field=models.FileField(blank=True, default='', help_text='Most recent degree/certificate (Matric/Inter/Bachelor as applicable).', upload_to='admission_docs/education/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='application',
            name='domicile_certificate',
            field=models.FileField(blank=True, help_text='Domicile certificate, if required by your program/quota.', null=True, upload_to='admission_docs/domicile/%Y/%m/'),
        ),
    ]
