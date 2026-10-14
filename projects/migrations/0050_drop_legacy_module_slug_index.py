from django.db import migrations


def drop_legacy_module_slug_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects_module'
              AND COLUMN_NAME = 'slug'
              AND INDEX_NAME != 'PRIMARY'
        """)
        for (index_name,) in cursor.fetchall():
            cursor.execute(f"ALTER TABLE projects_module DROP INDEX `{index_name}`")

        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects_module'
              AND COLUMN_NAME = 'slug'
        """)
        if cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE projects_module DROP COLUMN slug")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0049_subtask_due_date_and_more'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_module_slug_index, migrations.RunPython.noop),
    ]
