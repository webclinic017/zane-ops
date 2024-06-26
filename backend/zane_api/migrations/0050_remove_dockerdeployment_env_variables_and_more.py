# Generated by Django 5.0.2 on 2024-03-29 15:54

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "zane_api",
            "0049_archiveddockerenvvariables_archivedportconfiguration_and_more",
        ),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dockerdeployment",
            name="env_variables",
        ),
        migrations.RemoveField(
            model_name="gitrepositoryworker",
            name="env_variables",
        ),
        migrations.RemoveField(
            model_name="dockerregistryworker",
            name="env_variables",
        ),
        migrations.RemoveField(
            model_name="gitdeployment",
            name="env_variables",
        ),
        migrations.RemoveField(
            model_name="archiveddockerservice",
            name="env_variables",
        ),
        migrations.AddField(
            model_name="archiveddockerenvvariables",
            name="service",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="env_variables",
                to="zane_api.archiveddockerservice",
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="DockerEnvVariable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=255)),
                ("value", models.CharField(max_length=255)),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="env_variables",
                        to="zane_api.dockerregistryservice",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="GitEnvVariable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=255)),
                ("value", models.CharField(max_length=255)),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="env_variables",
                        to="zane_api.gitrepositoryservice",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.DeleteModel(
            name="EnvVariable",
        ),
    ]
