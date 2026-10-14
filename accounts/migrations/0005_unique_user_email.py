from django.db import migrations, models
from django.db.models import Count


def reject_duplicate_emails(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    duplicates = (
        User.objects.exclude(email='')
        .values('email')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
    )
    duplicate_emails = [row['email'] for row in duplicates]
    if duplicate_emails:
        raise RuntimeError(
            'Duplicate user emails must be resolved before applying this migration: '
            + ', '.join(duplicate_emails)
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_passwordresettoken'),
    ]

    operations = [
        migrations.RunPython(reject_duplicate_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(max_length=254, unique=True),
        ),
    ]
