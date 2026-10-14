from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_user_invite_status'),
        ('projects', '0045_separate_task_subtask_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='users',
            field=models.ManyToManyField(blank=True, related_name='client_companies', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='action',
            field=models.CharField(
                choices=[
                    ('issue_created', 'Issue Created'),
                    ('issue_updated', 'Issue Updated'),
                    ('issue_deleted', 'Issue Deleted'),
                    ('status_changed', 'Status Changed'),
                    ('comment_added', 'Comment Added'),
                    ('project_created', 'Project Created'),
                    ('project_updated', 'Project Updated'),
                    ('user_invited', 'User Invited'),
                    ('invite_resent', 'Invite Resent'),
                    ('user_updated', 'User Updated'),
                    ('role_changed', 'Role Changed'),
                    ('user_disabled', 'User Disabled'),
                    ('user_deleted', 'User Deleted'),
                    ('client_created', 'Client Created'),
                    ('client_updated', 'Client Updated'),
                    ('client_deleted', 'Client Deleted'),
                    ('assignee_changed', 'Assignee Changed'),
                ],
                max_length=30,
            ),
        ),
    ]
