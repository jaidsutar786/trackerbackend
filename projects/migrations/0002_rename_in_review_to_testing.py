# Generated migration to rename 'In Review' to 'Testing'

from django.db import migrations


def rename_status_forward(apps, schema_editor):
    """Rename 'In Review' to 'Testing' in existing records"""
    Issue = apps.get_model('projects', 'Issue')
    Feature = apps.get_model('projects', 'Feature')
    Task = apps.get_model('projects', 'Task')
    
    # Update Issues
    Issue.objects.filter(status='In Review').update(status='Testing')
    
    # Update Features (if they have In Review status)
    # Features don't have In Review in their STATUSES, so skip
    
    # Update Tasks (they have Testing already, no In Review)
    # Tasks don't have In Review in their STATUSES, so skip


def rename_status_backward(apps, schema_editor):
    """Revert 'Testing' back to 'In Review'"""
    Issue = apps.get_model('projects', 'Issue')
    
    # Revert Issues
    Issue.objects.filter(status='Testing').update(status='In Review')


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),  # Replace with your latest migration
    ]

    operations = [
        migrations.RunPython(rename_status_forward, rename_status_backward),
    ]
