# Generated by Django 4.1.7 on 2023-10-11 19:56

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0001_initial'),
        ('file_management', '0011_remove_folder_pscedclassification_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='subfolder',
            name='classification',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='records.classification'),
        ),
    ]