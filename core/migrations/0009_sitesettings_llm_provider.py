from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_accessibility_sms_outbox'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='llm_provider',
            field=models.CharField(
                choices=[('groq', 'Groq (free, fast - default)'), ('huggingface', 'Hugging Face Inference API (free tier)'), ('openai', 'OpenAI / ChatGPT (paid)'), ('anthropic', 'Anthropic / Claude (paid)')],
                default='groq', max_length=20,
            ),
        ),
    ]
