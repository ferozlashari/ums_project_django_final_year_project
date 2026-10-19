import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('registration', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GuardianLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('relation', models.CharField(choices=[('father', 'Father'), ('mother', 'Mother'), ('guardian', 'Guardian/Other')], default='guardian', max_length=20)),
                ('is_verified', models.BooleanField(default=False, help_text="Only verified links can view the student's data.")),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('guardian', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='guardian_links', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='guardian_links', to='registration.student')),
                ('verified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='guardianlink',
            unique_together={('guardian', 'student')},
        ),
    ]
