from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_sitesettings_payment_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='role',
            field=models.CharField(choices=[('student', 'Student'), ('faculty', 'Faculty'), ('staff', 'Staff'), ('admin', 'Admin'), ('guardian', 'Parent/Guardian')], default='student', max_length=20),
        ),
    ]
