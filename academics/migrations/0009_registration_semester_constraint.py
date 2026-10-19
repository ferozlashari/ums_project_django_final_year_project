from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('academics','0008_integrity_indexes')]
    operations = [
        migrations.RemoveConstraint(model_name='courseregistration', name='uniq_active_course_registration'),
        migrations.AddConstraint(model_name='courseregistration', constraint=models.UniqueConstraint(fields=('student','section','semester'), condition=models.Q(status='registered'), name='uniq_active_course_registration_semester')),
    ]
