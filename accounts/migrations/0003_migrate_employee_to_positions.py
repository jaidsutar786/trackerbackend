# Generated migration to convert employee role to position-based roles

from django.db import migrations


def migrate_employee_roles(apps, schema_editor):
    """Convert existing 'employee' users to 'frontend_developer' as default"""
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='employee').update(role='frontend_developer')


def reverse_migration(apps, schema_editor):
    """Reverse migration - convert position roles back to employee"""
    User = apps.get_model('accounts', 'User')
    position_roles = [
        'frontend_developer',
        'backend_developer', 
        'fullstack_developer',
        'devops',
        'qa_tester',
        'ui_ux_designer'
    ]
    User.objects.filter(role__in=position_roles).update(role='employee')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(migrate_employee_roles, reverse_migration),
    ]
