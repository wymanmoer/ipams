# Generated by Django 4.1.7 on 2023-10-12 17:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0004_remove_record_abstract_file_alter_recordfile_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='record',
            name='abstract_file',
            field=models.FileField(blank=True, default='', null=True, upload_to='abstract/'),
        ),
    ]