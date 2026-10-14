from django.db import migrations


def drop_slug_if_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'projects_module'
            AND column_name = 'slug'
        """)
        if cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE projects_module DROP COLUMN IF EXISTS slug")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0039_sync_module_model'),
    ]

    operations = [
        migrations.RunPython(drop_slug_if_exists, migrations.RunPython.noop),
    ]
