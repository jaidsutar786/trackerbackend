from django.db import migrations


def apply(apps, schema_editor):
    c = schema_editor.connection.cursor()
    c.execute("SET FOREIGN_KEY_CHECKS = 0")

    try:
        # 1. Create projects_subtask if not exists
        c.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='projects_subtask'")
        if not c.fetchone()[0]:
            c.execute("""
                CREATE TABLE `projects_subtask` (
                    `id` bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    `title` varchar(500) NOT NULL,
                    `description` longtext NOT NULL,
                    `status` varchar(20) NOT NULL DEFAULT 'To Do',
                    `priority` varchar(20) NOT NULL DEFAULT 'medium',
                    `created_at` datetime(6) NOT NULL,
                    `updated_at` datetime(6) NOT NULL,
                    `assignee_id` bigint NULL,
                    `created_by_id` bigint NULL,
                    `task_id` bigint NOT NULL,
                    CONSTRAINT `fk_subtask_assignee` FOREIGN KEY (`assignee_id`) REFERENCES `accounts_user`(`id`) ON DELETE SET NULL,
                    CONSTRAINT `fk_subtask_created_by` FOREIGN KEY (`created_by_id`) REFERENCES `accounts_user`(`id`) ON DELETE SET NULL,
                    CONSTRAINT `fk_subtask_task` FOREIGN KEY (`task_id`) REFERENCES `projects_task`(`id`) ON DELETE CASCADE
                )
            """)

        # 2. Drop indexes on projects_module, but keep any index that supports a foreign key
        c.execute("""
            SELECT DISTINCT s.INDEX_NAME
            FROM information_schema.STATISTICS s
            LEFT JOIN information_schema.TABLE_CONSTRAINTS tc
                ON tc.TABLE_SCHEMA = s.TABLE_SCHEMA
               AND tc.TABLE_NAME = s.TABLE_NAME
               AND tc.CONSTRAINT_NAME = s.INDEX_NAME
               AND tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
            WHERE s.TABLE_SCHEMA = DATABASE()
              AND s.TABLE_NAME = 'projects_module'
              AND s.INDEX_NAME != 'PRIMARY'
              AND tc.CONSTRAINT_NAME IS NULL
        """)
        for (idx,) in c.fetchall():
            try:
                c.execute(f"ALTER TABLE projects_module DROP INDEX `{idx}`")
            except Exception as exc:
                # MySQL can refuse to drop indexes that are still supporting a FK.
                # Keep going so the migration can finish on fresh/recreated databases.
                if getattr(exc, "args", None) and exc.args[0] == 1553:
                    continue
                raise

        # 3. Drop slug column if exists
        c.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='projects_module' AND COLUMN_NAME='slug'")
        if c.fetchone()[0]:
            c.execute("ALTER TABLE projects_module DROP COLUMN slug")

        # 4. Add unique index (project_id, module_id)
        c.execute("ALTER TABLE projects_module ADD UNIQUE KEY `projects_module_project_id_module_id_uniq` (project_id, module_id(20))")

        # 5. Add regular index (project_id, module_id)
        c.execute("ALTER TABLE projects_module ADD INDEX `projects_mo_project_f1a5f6_idx` (project_id, module_id(20))")
    finally:
        c.execute("SET FOREIGN_KEY_CHECKS = 1")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0040_remove_module_slug'),
    ]

    operations = [
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
