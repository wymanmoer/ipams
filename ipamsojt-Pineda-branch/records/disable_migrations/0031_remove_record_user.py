# Generated by Django 4.1.7 on 2023-10-26 02:02

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0030_alter_record_adviser_alter_record_user'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='record',
            name='user',
        ),
    ]
