# Generated by Django 5.0.4 on 2024-05-08 17:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0095_rename_deployment_status_dockerdeployment_status_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dockerregistryservice",
            name="network_alias",
            field=models.CharField(max_length=300, null=True),
        ),
        migrations.AddField(
            model_name="gitrepositoryservice",
            name="network_alias",
            field=models.CharField(max_length=300, null=True),
        ),
    ]