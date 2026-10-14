# Generated migration to change Issue title from CharField to TextField

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0019_issuecomment_likes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='issue',
            name='title',
            field=models.TextField(db_column='title'),
        ),
    ]
