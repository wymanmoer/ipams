# Generated by Django 4.1.7 on 2023-09-26 20:23

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('records', '0001_initial'),
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='userrecord',
            name='record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='records.record'),
        ),
        migrations.AddField(
            model_name='userrecord',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='setting',
            name='set_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='rolerequest',
            name='role',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.userrole'),
        ),
        migrations.AddField(
            model_name='rolerequest',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='log',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='department',
            name='college',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.college'),
        ),
        migrations.AddField(
            model_name='course',
            name='department',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.department'),
        ),
        migrations.AddField(
            model_name='user',
            name='groups',
            field=models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups'),
        ),
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.ForeignKey(default=7, on_delete=django.db.models.deletion.CASCADE, to='accounts.userrole'),
        ),
        migrations.AddField(
            model_name='user',
            name='user_permissions',
            field=models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions'),
        ),
        migrations.AddField(
            model_name='student',
            name='course',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='accounts.course'),
        ),
        migrations.AddField(
            model_name='adviser',
            name='college',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.college'),
        ),
        migrations.AddField(
            model_name='adviser',
            name='department',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.department'),
        ),
    ]
