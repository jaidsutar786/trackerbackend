import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0004_issuescreenshot'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add project_key and slug to Project
        migrations.AddField(
            model_name='project',
            name='project_key',
            field=models.CharField(blank=True, default='', max_length=10, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='project',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=255),
        ),

        # Feature model
        migrations.CreateModel(
            name='Feature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feature_id', models.CharField(blank=True, max_length=20)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('status', models.CharField(
                    choices=[('To Do', 'To Do'), ('In Progress', 'In Progress'), ('Done', 'Done')],
                    default='To Do', max_length=20,
                )),
                ('priority', models.CharField(
                    choices=[('highest', 'Highest'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
                    default='medium', max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assignee', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_features',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='features',
                    to='projects.project',
                )),
                ('reporter', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reported_features',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['feature_id']},
        ),

        # Task model
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(blank=True, max_length=20)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('status', models.CharField(
                    choices=[('To Do', 'To Do'), ('In Progress', 'In Progress'), ('Done', 'Done')],
                    default='To Do', max_length=20,
                )),
                ('priority', models.CharField(
                    choices=[('highest', 'Highest'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
                    default='medium', max_length=20,
                )),
                ('due_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assignee', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_tasks',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('feature', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tasks',
                    to='projects.feature',
                )),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tasks',
                    to='projects.project',
                )),
                ('reporter', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reported_tasks',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['task_id']},
        ),
    ]
