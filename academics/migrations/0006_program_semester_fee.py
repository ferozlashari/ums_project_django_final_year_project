from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0005_semester_number_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='program',
            name='semester_fee',
            field=models.DecimalField(decimal_places=2, default=45000, help_text='Per-semester tuition fee for this program - used by student self-service fee-challan generation.', max_digits=10),
        ),
    ]
