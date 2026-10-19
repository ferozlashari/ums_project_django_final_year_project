from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('onlineclass','0002_alter_onlineclass_options'),('academics','0014_alter_coursesection_options_alter_faculty_options')]
    operations=[
        migrations.AddField(model_name='onlineclass',name='semester',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name='online_classes',to='academics.semester')),
    ]
