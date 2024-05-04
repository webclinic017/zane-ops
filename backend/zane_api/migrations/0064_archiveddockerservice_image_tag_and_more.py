# Generated by Django 5.0.2 on 2024-04-26 12:07

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0063_alter_dockerdeployment_image_tag"),
    ]

    operations = [
        migrations.AddField(
            model_name="archiveddockerservice",
            name="image_tag",
            field=models.CharField(default="latest", max_length=255),
        ),
        migrations.AlterField(
            model_name="dockerdeployment",
            name="service",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="deployments",
                to="zane_api.dockerregistryservice",
            ),
        ),
    ]