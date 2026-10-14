import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_unique_user_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='invite_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('sent', 'Sent'),
                    ('failed', 'Failed'),
                    ('accepted', 'Accepted'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='invite_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='invited_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invited_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
