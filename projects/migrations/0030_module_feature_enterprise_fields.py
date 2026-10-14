from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0029_taskcommentattachment'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='module',
            options={'ordering': ['sort_order', '-created_at']},
        ),
        migrations.AlterModelOptions(
            name='feature',
            options={'ordering': ['sort_order', 'feature_id']},
        ),
        migrations.AddField(
            model_name='module',
            name='business_owner',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='module',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='module',
            name='objective',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='module',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='module',
            name='planned_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='module',
            name='planned_start_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='module',
            name='priority',
            field=models.CharField(choices=[('highest', 'Highest'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('lowest', 'Lowest')], default='medium', max_length=20),
        ),
        migrations.AddField(
            model_name='module',
            name='sort_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='module',
            name='status',
            field=models.CharField(choices=[('Planned', 'Planned'), ('In Progress', 'In Progress'), ('On Hold', 'On Hold'), ('Done', 'Done')], default='Planned', max_length=20),
        ),
        migrations.AddField(
            model_name='feature',
            name='backend_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='feature',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='feature',
            name='frontend_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='feature',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sub_features', to='projects.feature'),
        ),
        migrations.AddField(
            model_name='feature',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='feature',
            name='priority',
            field=models.CharField(choices=[('highest', 'Highest'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('lowest', 'Lowest')], default='medium', max_length=20),
        ),
        migrations.AddField(
            model_name='feature',
            name='requirement_type',
            field=models.CharField(choices=[('changes_existing', 'Changes in Existing'), ('new_card', 'New Card'), ('new_screen', 'New Screen'), ('new_chart', 'New Chart'), ('new_table', 'New Table'), ('integration', 'Integration'), ('report', 'Report'), ('other', 'Other')], default='changes_existing', max_length=32),
        ),
        migrations.AddField(
            model_name='feature',
            name='sort_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='feature',
            name='status',
            field=models.CharField(choices=[('To Do', 'To Do'), ('In Progress', 'In Progress'), ('Testing', 'Testing'), ('Blocked', 'Blocked'), ('Done', 'Done')], default='To Do', max_length=20),
        ),
        migrations.AddIndex(
            model_name='module',
            index=models.Index(fields=['project', 'status'], name='projects_mo_project_9388bc_idx'),
        ),
        migrations.AddIndex(
            model_name='module',
            index=models.Index(fields=['project', 'phase'], name='projects_mo_project_78eb09_idx'),
        ),
        migrations.AddIndex(
            model_name='feature',
            index=models.Index(fields=['module', 'parent'], name='projects_fe_module__10a4ec_idx'),
        ),
    ]
