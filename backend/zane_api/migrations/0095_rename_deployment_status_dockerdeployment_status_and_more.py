# Generated by Django 5.0.4 on 2024-05-08 17:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0094_alter_gitrepositoryworker_unique_together_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="dockerdeployment",
            old_name="deployment_status",
            new_name="status",
        ),
        migrations.AddField(
            model_name="dockerdeployment",
            name="network_alias",
            field=models.CharField(max_length=300, null=True),
        ),
        migrations.AddField(
            model_name="dockerdeployment",
            name="slot",
            field=models.CharField(
                choices=[("BLUE", "Blue"), ("GREEN", "Green")],
                default="BLUE",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="gitdeployment",
            name="network_alias",
            field=models.CharField(max_length=300, null=True),
        ),
    ]
