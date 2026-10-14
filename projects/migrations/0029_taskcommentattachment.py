from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0028_add_developer_to_task'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskCommentAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='task_comment_attachments/')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('comment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='projects.taskcomment')),
            ],
            options={
                'ordering': ['uploaded_at'],
            },
        ),
    ]
