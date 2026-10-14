from django.db import OperationalError, migrations


def drop_slug_if_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'projects_module' 
            AND COLUMN_NAME = 'slug'
        """)
        if not cursor.fetchone()[0]:
            return
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects_module'
              AND COLUMN_NAME = 'slug'
            """
        )
        if cursor.fetchone()[0]:
            try:
                cursor.execute("ALTER TABLE projects_module DROP COLUMN slug")
            except OperationalError as exc:
                if exc.args[0] != 1072:
                    raise
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0039_sync_module_model'),
    ]

    operations = [
        migrations.RunPython(drop_slug_if_exists, migrations.RunPython.noop),
    ]
