from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='project_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='feature_id',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='task_id',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('issue_created',        'Issue Created'),
                    ('issue_assigned',       'Issue Assigned'),
                    ('issue_status_changed', 'Issue Status Changed'),
                    ('issue_comment',        'Issue Comment'),
                    ('project_assigned',     'Project Assigned'),
                    ('feature_assigned',     'Feature Assigned'),
                    ('task_assigned',        'Task Assigned'),
                    ('task_completed',       'Task Completed'),
                ],
                max_length=30,
            ),
        ),
    ]
