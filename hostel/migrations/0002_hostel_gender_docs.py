import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hostel', '0001_initial'),
        ('registration', '0004_student_gender'),
    ]

    operations = [
        migrations.CreateModel(
            name='Hostel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. "Iqbal Hall", "Fatima Jinnah Hostel"', max_length=150)),
                ('gender', models.CharField(choices=[('male', "Boys' Hostel"), ('female', "Girls' Hostel")], max_length=10)),
                ('warden_name', models.CharField(blank=True, max_length=150)),
                ('warden_phone', models.CharField(blank=True, max_length=20)),
                ('address', models.CharField(blank=True, max_length=255)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.AddField(
            model_name='room',
            name='hostel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='rooms', to='hostel.hostel'),
        ),
        migrations.AddField(
            model_name='hostelapplication',
            name='hostel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='applications', to='hostel.hostel'),
        ),
        migrations.AddField(
            model_name='hostelapplication',
            name='cnic_copy',
            field=models.FileField(blank=True, default='', help_text='Scanned copy of CNIC/B-Form.', upload_to='hostel_docs/cnic/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='hostelapplication',
            name='guardian_consent_letter',
            field=models.FileField(blank=True, help_text='Signed guardian consent letter (required for undergraduate applicants).', null=True, upload_to='hostel_docs/consent/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='hostelapplication',
            name='medical_certificate',
            field=models.FileField(blank=True, help_text='Recent medical fitness certificate, if your campus requires one.', null=True, upload_to='hostel_docs/medical/%Y/%m/'),
        ),
    ]
