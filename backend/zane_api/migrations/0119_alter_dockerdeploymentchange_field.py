# Generated by Django 5.0.4 on 2024-05-31 23:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "zane_api",
            "0118_alter_dockerenvvariable_key_alter_gitenvvariable_key_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="dockerdeploymentchange",
            name="field",
            field=models.CharField(
                choices=[
                    ("image", "image"),
                    ("command", "command"),
                    ("credentials", "credentials"),
                    ("healthcheck", "healthcheck"),
                    ("volumes", "volumes"),
                    ("env_variables", "env_variables"),
                    ("urls", "urls"),
                    ("ports", "ports"),
                ],
                max_length=255,
            ),
        ),
    ]