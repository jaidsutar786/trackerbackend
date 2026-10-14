from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0030_module_feature_enterprise_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='feature',
            name='points',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
