from django.db import migrations


def drop_legacy_project_only_unique_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects_module'
            GROUP BY INDEX_NAME
            HAVING INDEX_NAME LIKE '%slug%'
               OR (
                    COUNT(*) = 1
                    AND MAX(COLUMN_NAME) = 'project_id'
                    AND MAX(NON_UNIQUE) = 0
                    AND INDEX_NAME != 'PRIMARY'
               )
        """)
        for (index_name,) in cursor.fetchall():
            cursor.execute(f"ALTER TABLE projects_module DROP INDEX `{index_name}`")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0050_drop_legacy_module_slug_index'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_project_only_unique_index, migrations.RunPython.noop),
    ]
