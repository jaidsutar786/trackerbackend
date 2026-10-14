from django.db import migrations, models


def renumber_task_and_subtask_keys(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    Task = apps.get_model('projects', 'Task')
    SubTask = apps.get_model('projects', 'SubTask')

    for task in Task.objects.all().only('id', 'task_id'):
        task.task_id = f'TMP-TASK-{task.id}'
        task.save(update_fields=['task_id'])

    for project in Project.objects.all().order_by('id'):
        project_code = (project.project_key or project.name[:6] or 'PRJ').upper()
        tasks = Task.objects.filter(project_id=project.id).order_by('created_at', 'id')
        for index, task in enumerate(tasks, start=1):
            task.task_id = f'{project_code}-{index}'
            task.save(update_fields=['task_id'])

    for task in Task.objects.all().order_by('project_id', 'created_at', 'id'):
        subtasks = SubTask.objects.filter(task_id=task.id).order_by('created_at', 'id')
        for index, subtask in enumerate(subtasks, start=1):
            subtask.subtask_id = f'{task.task_id}-S{index}'
            subtask.save(update_fields=['subtask_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0044_add_likes_to_task_and_subtask_comments'),
    ]

    operations = [
        migrations.AddField(
            model_name='subtask',
            name='subtask_id',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.RunPython(renumber_task_and_subtask_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='subtask',
            constraint=models.UniqueConstraint(fields=('task', 'subtask_id'), name='unique_subtask_id_per_task'),
        ),
        migrations.AddIndex(
            model_name='subtask',
            index=models.Index(fields=['task', 'subtask_id'], name='projects_su_task_id_a603a3_idx'),
        ),
    ]
