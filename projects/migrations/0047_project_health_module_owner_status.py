import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0046_client_users_activitylog_user_actions'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='status',
            field=models.CharField(
                choices=[
                    ('planning', 'Planning'),
                    ('active', 'Active'),
                    ('on_hold', 'On Hold'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='planning',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='project',
            name='risk',
            field=models.CharField(
                choices=[
                    ('low', 'Low'),
                    ('medium', 'Medium'),
                    ('high', 'High'),
                    ('critical', 'Critical'),
                ],
                default='low',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='project',
            name='blockers',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='project',
            name='health_summary',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='module',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='owned_modules',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='module',
            name='status',
            field=models.CharField(
                choices=[
                    ('planned', 'Planned'),
                    ('active', 'Active'),
                    ('blocked', 'Blocked'),
                    ('done', 'Done'),
                ],
                default='planned',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='module',
            name='health_summary',
            field=models.TextField(blank=True, default=''),
        ),
    ]
