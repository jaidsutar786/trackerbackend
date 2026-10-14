from django.db import migrations
from django.utils.text import slugify


def project_code(project):
    return (project.project_key or slugify(project.name).upper()[:6] or 'PRJ').upper()


def module_code_from_slug(module):
    parts = (module.slug or '').split('-')
    if len(parts) >= 2 and parts[1].startswith('m') and parts[1][1:].isdigit():
        return parts[1].upper()
    return ''


def rebuild_module_and_feature_keys(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    Module = apps.get_model('projects', 'Module')
    Feature = apps.get_model('projects', 'Feature')

    for feature in Feature.objects.all():
        feature.feature_id = f'TMP-{feature.id}'
        feature.save(update_fields=['feature_id'])

    for project in Project.objects.all():
        code = project_code(project)
        used_slugs = set()
        modules = Module.objects.filter(project=project).order_by('sort_order', 'created_at', 'id')
        module_numbers = {}

        for index, module in enumerate(modules, start=1):
            module_numbers[module.id] = index
            title_slug = slugify(module.title) or 'module'
            base_slug = f'{code.lower()}-m{index:02d}-{title_slug}'
            candidate = base_slug
            suffix = 2
            while candidate in used_slugs:
                candidate = f'{base_slug}-{suffix}'
                suffix += 1
            used_slugs.add(candidate)
            module.slug = candidate
            module.save(update_fields=['slug'])

        for module in modules:
            module_code = module_code_from_slug(module) or f'M{module_numbers.get(module.id, module.id):02d}'
            features = Feature.objects.filter(project=project, module=module).order_by('sort_order', 'created_at', 'id')
            for index, feature in enumerate(features, start=1):
                feature.feature_id = f'{code}-{module_code}-F{index:02d}'
                feature.save(update_fields=['feature_id'])

        loose_features = Feature.objects.filter(project=project, module__isnull=True).order_by('sort_order', 'created_at', 'id')
        for index, feature in enumerate(loose_features, start=1):
            feature.feature_id = f'{code}-F{index:02d}'
            feature.save(update_fields=['feature_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0034_remove_feature_projects_fe_module__10a4ec_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(rebuild_module_and_feature_keys, migrations.RunPython.noop),
        migrations.RunSQL('DROP TABLE IF EXISTS projects_subtask;', reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL('DROP TABLE IF EXISTS projects_timeentry;', reverse_sql=migrations.RunSQL.noop),
    ]
