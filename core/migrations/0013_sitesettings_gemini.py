from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('core','0012_sitesettings_local_ai')]
    operations = [
        migrations.AlterField(
            model_name='sitesettings', name='llm_provider',
            field=models.CharField(max_length=20, choices=[('local','Built-in Local Assistant (zero cost)'),('groq','Groq (optional free tier)'),('huggingface','Hugging Face (optional free tier)'),('gemini','Google Gemini (optional free tier)')], default='local'),
        ),
    ]
