from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0037_remove_unused_module_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='module',
            name='module_id',
            field=models.CharField(max_length=20, blank=True, default=''),
        ),
        migrations.RunSQL(
            "UPDATE projects_module SET module_id = CONCAT(UPPER(p.project_key), '-M', LPAD(projects_module.id::text, 2, '0')) FROM projects_project p WHERE projects_module.project_id = p.id AND projects_module.module_id = ''",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
