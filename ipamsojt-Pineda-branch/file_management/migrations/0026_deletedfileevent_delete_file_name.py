# Generated by Django 4.1.7 on 2023-10-20 00:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('file_management', '0025_remove_deletedfileevent_delete_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='deletedfileevent',
            name='delete_file_name',
            field=models.CharField(default='', max_length=255),
        ),
    ]
