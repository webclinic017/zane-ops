# Generated by Django 5.0.4 on 2024-09-02 18:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0153_archiveddockerservice_healthcheck_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="archiveddockerservice",
            name="deployments",
            field=models.JSONField(default=list),
        ),
    ]