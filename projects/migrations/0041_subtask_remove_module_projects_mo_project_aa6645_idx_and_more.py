from django.db import migrations


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    c = schema_editor.connection.cursor()

    # 1. Create projects_subtask if not exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects_subtask (
            id bigserial PRIMARY KEY,
            title varchar(500) NOT NULL,
            description text NOT NULL DEFAULT '',
            status varchar(20) NOT NULL DEFAULT 'To Do',
            priority varchar(20) NOT NULL DEFAULT 'medium',
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            assignee_id bigint NULL REFERENCES accounts_user(id) ON DELETE SET NULL,
            created_by_id bigint NULL REFERENCES accounts_user(id) ON DELETE SET NULL,
            task_id bigint NOT NULL REFERENCES projects_task(id) ON DELETE CASCADE
        )
    """)

    # 2. Drop all non-FK, non-PK indexes on projects_module
    c.execute("""
        SELECT i.relname
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        WHERE t.relname = 'projects_module'
          AND NOT ix.indisprimary
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint con
              WHERE con.conindid = ix.indexrelid
                AND con.contype = 'f'
          )
    """)
    for (idx,) in c.fetchall():
        c.execute(f'DROP INDEX IF EXISTS "{idx}"')

    # 3. Drop slug column if exists
    c.execute("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = 'projects_module' AND column_name = 'slug'
    """)
    if c.fetchone()[0]:
        c.execute("ALTER TABLE projects_module DROP COLUMN IF EXISTS slug")

    # 4. Add unique index (project_id, module_id)
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS projects_module_project_id_module_id_uniq
        ON projects_module (project_id, module_id)
    """)

    # 5. Add regular index (project_id, module_id)
    c.execute("""
        CREATE INDEX IF NOT EXISTS projects_mo_project_f1a5f6_idx
        ON projects_module (project_id, module_id)
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0040_remove_module_slug'),
    ]

    operations = [
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
