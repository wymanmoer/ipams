# Generated by Django 4.1.7 on 2023-10-20 00:17

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0012_alter_recordfile_record_file_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='recordfile',
            name='download_count',
        ),
    ]
