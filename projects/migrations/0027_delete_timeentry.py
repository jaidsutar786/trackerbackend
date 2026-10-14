from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0026_timeentry'),
    ]

    operations = [
        migrations.DeleteModel(
            name='TimeEntry',
        ),
    ]
