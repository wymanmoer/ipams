# Generated by Django 4.1.7 on 2023-10-20 03:55

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('records', '0013_remove_recordfile_download_count'),
        ('file_management', '0026_deletedfileevent_delete_file_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='FileRenameEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('old_file_name', models.CharField(max_length=255)),
                ('new_file_name', models.CharField(max_length=255)),
                ('rename_time', models.DateTimeField(auto_now=True)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='records.record')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
