# Generated by Django 5.0.4 on 2024-05-19 02:15

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0101_project_description"),
    ]

    operations = [
        migrations.RenameField(
            model_name="gitdeployment",
            old_name="deployment_status",
            new_name="status",
        ),
        migrations.RenameField(
            model_name="gitdeployment",
            old_name="deployment_status_reason",
            new_name="status_reason",
        ),
    ]
