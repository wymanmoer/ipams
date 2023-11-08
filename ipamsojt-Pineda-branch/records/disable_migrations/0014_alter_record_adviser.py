# Generated by Django 4.1.7 on 2023-10-23 02:23

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_initial'),
        ('records', '0013_remove_recordfile_download_count'),
    ]

    operations = [
        migrations.AlterField(
            model_name='record',
            name='adviser',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='accounts.adviser'),
        ),
    ]