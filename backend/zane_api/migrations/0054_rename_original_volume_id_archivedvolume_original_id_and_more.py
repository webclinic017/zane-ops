# Generated by Django 5.0.2 on 2024-03-30 06:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zane_api", "0053_archivedvolume_original_volume_id"),
    ]

    operations = [
        migrations.RenameField(
            model_name="archivedvolume",
            old_name="original_volume_id",
            new_name="original_id",
        ),
        migrations.AddField(
            model_name="archiveddockerservice",
            name="original_id",
            field=models.CharField(max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="archivedproject",
            name="original_id",
            field=models.CharField(max_length=255),
            preserve_default=False,
        ),
    ]
