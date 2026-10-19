import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('registration', '0003_student_address_student_cnic_student_phone'),
    ]

    operations = [
        migrations.CreateModel(
            name='Vehicle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('registration_no', models.CharField(max_length=30, unique=True)),
                ('capacity', models.PositiveIntegerField(default=40)),
                ('driver_name', models.CharField(blank=True, max_length=150)),
                ('driver_phone', models.CharField(blank=True, max_length=20)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['registration_no']},
        ),
        migrations.CreateModel(
            name='Route',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('fare_per_semester', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('is_active', models.BooleanField(default=True)),
                ('vehicle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='routes', to='transport.vehicle')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='RouteStop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. "Main Gate", "Askari Chowk"', max_length=150)),
                ('pickup_time', models.TimeField()),
                ('order', models.PositiveIntegerField(default=0, help_text='Stop order along the route (1 = first).')),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stops', to='transport.route')),
            ],
            options={'ordering': ['route', 'order']},
        ),
        migrations.CreateModel(
            name='StudentTransportAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True)),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='transport.route')),
                ('stop', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='transport.routestop')),
                ('student', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='transport_assignment', to='registration.student')),
            ],
        ),
    ]
