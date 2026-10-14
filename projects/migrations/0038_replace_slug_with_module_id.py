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
            "UPDATE projects_module m JOIN projects_project p ON m.project_id = p.id SET m.module_id = CONCAT(UPPER(p.project_key), '-M', LPAD(m.id, 2, '0')) WHERE m.module_id = ''",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
