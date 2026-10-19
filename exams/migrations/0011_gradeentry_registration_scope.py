from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('exams','0010_dynamic_assessment'),('academics','0014_alter_coursesection_options_alter_faculty_options')]
    operations=[migrations.AddField(model_name='gradeentry',name='registration',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='grade_entries',to='academics.courseregistration'))]
