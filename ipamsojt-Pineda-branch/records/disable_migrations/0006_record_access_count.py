# Generated by Django 4.1.7 on 2023-10-13 01:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0005_record_abstract_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='record',
            name='access_count',
            field=models.IntegerField(default=0),
        ),
    ]
