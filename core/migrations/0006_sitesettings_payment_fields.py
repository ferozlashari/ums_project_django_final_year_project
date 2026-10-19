from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_notification'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='bank_name',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='bank_account_title',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='bank_account_no',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='bank_iban',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='jazzcash_number',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='JazzCash mobile account number'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='easypaisa_number',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='EasyPaisa mobile account number'),
        ),
    ]
