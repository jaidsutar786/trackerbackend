import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0003_activitylog'),
    ]

    operations = [
        migrations.CreateModel(
            name='IssueScreenshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='issue_screenshots/')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('issue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='screenshots', to='projects.issue')),
            ],
            options={
                'ordering': ['uploaded_at'],
            },
        ),
    ]
