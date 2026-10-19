from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('exams', '0007_alter_gradeentry_assignment_marks_and_more'), ('academics', '0014_alter_coursesection_options_alter_faculty_options')]
    operations = [
        migrations.CreateModel(name='AssessmentScheme', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(default='Standard Assessment Scheme', max_length=150)), ('version', models.PositiveIntegerField(default=1)), ('is_active', models.BooleanField(default=True)), ('created_at', models.DateTimeField(auto_now_add=True)),
            ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assessment_schemes', to='academics.course')),
        ], options={'ordering':['course','-version']}),
        migrations.CreateModel(name='AssessmentComponent', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=100)), ('component_type', models.CharField(choices=[('attendance','Attendance'),('quiz','Quiz'),('assignment','Assignment'),('lab','Lab'),('midterm','Midterm'),('project','Project'),('viva','Viva'),('presentation','Presentation'),('practical','Practical'),('final','Final Exam'),('other','Other')], default='other', max_length=30)),
            ('weight', models.DecimalField(decimal_places=2, max_digits=5)), ('max_marks', models.DecimalField(decimal_places=2, default=100, max_digits=7)), ('order', models.PositiveSmallIntegerField(default=1)), ('is_required', models.BooleanField(default=True)),
            ('scheme', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='components', to='exams.assessmentscheme')),
        ], options={'ordering':['order','id']}),
        migrations.CreateModel(name='AssessmentMark', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('raw_marks', models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)), ('entered_at', models.DateTimeField(auto_now=True)), ('verified_at', models.DateTimeField(blank=True, null=True)), ('published_at', models.DateTimeField(blank=True, null=True)),
            ('component', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='marks', to='exams.assessmentcomponent')),
            ('entered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
            ('registration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assessment_marks', to='academics.courseregistration')),
        ], options={'indexes':[models.Index(fields=['registration','component'], name='exams_assess_registration_component_idx')]}),
        migrations.CreateModel(name='ResultPublication', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('status', models.CharField(choices=[('teacher_submitted','Teacher Submitted'),('department_verified','Department Verified'),('exam_verified','Exam Office Verified'),('published','Published'),('reopened','Reopened')], default='teacher_submitted', max_length=30)),
            ('submitted_at', models.DateTimeField(auto_now_add=True)), ('verified_at', models.DateTimeField(blank=True, null=True)), ('published_at', models.DateTimeField(blank=True, null=True)), ('remarks', models.TextField(blank=True)),
            ('registration', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='result_publication', to='academics.courseregistration')),
            ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
        ]),
        migrations.AddConstraint(model_name='assessmentscheme', constraint=models.UniqueConstraint(fields=('course','version'), name='uniq_assessment_scheme_version')),
        migrations.AddConstraint(model_name='assessmentcomponent', constraint=models.UniqueConstraint(fields=('scheme','name'), name='uniq_assessment_component_name')),
        migrations.AddConstraint(model_name='assessmentmark', constraint=models.UniqueConstraint(fields=('registration','component'), name='uniq_registration_component_mark')),
    ]
