from django.db import migrations, models


def set_local_provider(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    SiteSettings.objects.filter(pk=1).update(llm_provider='local')


def reverse_provider(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    SiteSettings.objects.filter(pk=1).update(llm_provider='groq')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0011_security_controls'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesettings',
            name='llm_provider',
            field=models.CharField(
                choices=[
                    ('local', 'Built-in Local Assistant (zero cost)'),
                    ('groq', 'Groq (optional free tier)'),
                    ('huggingface', 'Hugging Face (optional free tier)'),
                ],
                default='local',
                max_length=20,
            ),
        ),
        migrations.RunPython(set_local_provider, reverse_provider),
    ]
