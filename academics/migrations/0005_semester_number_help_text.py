from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0004_courseregistration'),
    ]

    operations = [
        migrations.AlterField(
            model_name='semester',
            name='semester_number',
            field=models.PositiveSmallIntegerField(blank=True, help_text='1st-10th semester of the program (odd = Fall, even = Spring).', null=True),
        ),
    ]
