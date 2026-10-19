import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_profile_role_guardian'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='high_contrast_mode',
            field=models.BooleanField(default=False, verbose_name='High-contrast, larger-text display'),
        ),
        migrations.AddField(
            model_name='profile',
            name='text_only_mode',
            field=models.BooleanField(default=False, verbose_name='Low-bandwidth text-only layout (hides images/charts)'),
        ),
        migrations.AddField(
            model_name='profile',
            name='sms_fallback_number',
            field=models.CharField(blank=True, help_text='Critical alerts (fee due, exam schedule) will be queued for SMS delivery here if a real SMS gateway (e.g. Twilio) is wired in.', max_length=20, verbose_name='SMS fallback number'),
        ),
        migrations.CreateModel(
            name='SMSOutboxMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(max_length=20)),
                ('message', models.CharField(max_length=320)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent', models.BooleanField(default=False, help_text='Set True once a real SMS gateway is wired in and confirms delivery.')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sms_outbox', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
