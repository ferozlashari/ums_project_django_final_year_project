import core.upload_validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assignments', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='submission',
            name='file',
            field=models.FileField(blank=True, null=True, upload_to='assignment_submissions/%Y/%m/', validators=[core.upload_validators.validate_assignment_upload]),
        ),
    ]
