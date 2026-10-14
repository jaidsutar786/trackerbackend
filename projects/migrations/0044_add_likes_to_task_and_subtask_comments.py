# Generated migration to add likes field to TaskComment and SubTaskComment

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0043_add_subtask_comments'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskcomment',
            name='likes',
            field=models.ManyToManyField(blank=True, related_name='liked_task_comments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='subtaskcomment',
            name='likes',
            field=models.ManyToManyField(blank=True, related_name='liked_subtask_comments', to=settings.AUTH_USER_MODEL),
        ),
    ]
