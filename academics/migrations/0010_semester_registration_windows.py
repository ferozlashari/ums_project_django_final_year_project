from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('academics','0009_registration_semester_constraint')]
    operations = [
        migrations.AddField(model_name='semester', name='registration_open', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='semester', name='registration_close', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='semester', name='exam_registration_open', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='semester', name='exam_registration_close', field=models.DateTimeField(blank=True, null=True)),
    ]
