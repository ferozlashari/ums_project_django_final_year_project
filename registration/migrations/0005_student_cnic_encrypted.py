import core.encrypted_fields
import registration.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0004_student_gender'),
    ]

    operations = [
        migrations.AlterField(
            model_name='student',
            name='cnic',
            field=core.encrypted_fields.EncryptedCharField(blank=True, help_text='Format: 12345-1234567-1', max_length=500, validators=[registration.models.cnic_validator], verbose_name='CNIC / National ID'),
        ),
    ]
