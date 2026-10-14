from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0024_feature_projects_fe_project_b45f5b_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='issuescreenshot',
            name='comment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='comment_screenshots',
                to='projects.issuecomment',
            ),
        ),
    ]
