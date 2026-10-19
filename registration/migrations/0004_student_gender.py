from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0003_student_address_student_cnic_student_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='gender',
            field=models.CharField(blank=True, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other/Prefer not to say')], help_text='Used to match gender-specific hostel availability.', max_length=10),
        ),
    ]
