# Generated by Django 4.1.7 on 2023-10-26 01:51

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('records', '0025_record_user'),
    ]

    operations = [
        migrations.AlterField(
            model_name='record',
            name='adviser',
            field=models.ForeignKey(blank=True, default='', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='advised_records', to=settings.AUTH_USER_MODEL),
        ),
    ]
