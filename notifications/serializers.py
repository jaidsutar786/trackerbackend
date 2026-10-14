from rest_framework import serializers
from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    actor_role = serializers.SerializerMethodField()
    issue_id = serializers.SerializerMethodField()
    project_id = serializers.SerializerMethodField()
    feature_id = serializers.SerializerMethodField()
    task_id = serializers.SerializerMethodField()
    subtask_id = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    feature = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()
    subtask = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = ['id', 'notification_type', 'title', 'message', 'icon', 'read',
                  'issue_id', 'project_id', 'feature_id', 'task_id', 'subtask_id', 'created_at',
                  'actor_name', 'actor_role', 'issue', 'project', 'feature', 'task', 'subtask']

    def get_actor_name(self, obj):
        if not obj.actor:
            return None
        return obj.actor.get_full_name() or obj.actor.username

    def get_actor_role(self, obj):
        return obj.actor.role if obj.actor else None

    def get_issue_id(self, obj):
        return obj.issue_id

    def get_project_id(self, obj):
        return obj.project_id

    def get_feature_id(self, obj):
        return obj.feature.feature_id if obj.feature else None

    def get_task_id(self, obj):
        return obj.task.task_id if obj.task else None

    def get_subtask_id(self, obj):
        return obj.subtask.id if obj.subtask else None

    def get_issue(self, obj):
        if not obj.issue:
            return None
        return {
            'id': obj.issue.id,
            'title': obj.issue.title,
            'status': obj.issue.status,
            'priority': obj.issue.priority,
            'project_id': obj.issue.project_id,
        }

    def get_project(self, obj):
        if not obj.project:
            return None
        return {
            'id': obj.project.id,
            'name': obj.project.name,
            'slug': obj.project.slug,
            'project_key': obj.project.project_key,
        }

    def get_feature(self, obj):
        if not obj.feature:
            return None
        return {
            'id': obj.feature.id,
            'feature_id': obj.feature.feature_id,
            'title': obj.feature.title,
            'status': obj.feature.status,
            'project_id': obj.feature.project_id,
            'module_id': obj.feature.module_id,
        }

    def get_task(self, obj):
        if not obj.task:
            return None
        return {
            'id': obj.task.id,
            'task_id': obj.task.task_id,
            'title': obj.task.title,
            'status': obj.task.status,
            'priority': obj.task.priority,
            'project_id': obj.task.project_id,
            'feature_id': obj.task.feature_id,
            'module_id': obj.task.module_id,
        }

    def get_subtask(self, obj):
        if not obj.subtask:
            return None
        return {
            'id': obj.subtask.id,
            'title': obj.subtask.title,
            'status': obj.subtask.status,
            'priority': obj.subtask.priority,
            'task_id': obj.subtask.task_id,
            'task_title': obj.subtask.task.title,
            'project_id': obj.subtask.task.project_id,
        }


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    available_types = serializers.SerializerMethodField()

    class Meta:
        model = NotificationPreference
        fields = [
            'in_app_enabled', 'email_enabled', 'email_digest',
            'enabled_types', 'muted_types', 'available_types', 'updated_at',
        ]
        read_only_fields = ['available_types', 'updated_at']

    def get_available_types(self, obj):
        return [
            {'value': value, 'label': label}
            for value, label in Notification.NOTIFICATION_TYPES
        ]

    def validate_enabled_types(self, value):
        return self._validate_types(value)

    def validate_muted_types(self, value):
        return self._validate_types(value)

    def _validate_types(self, value):
        valid = {item[0] for item in Notification.NOTIFICATION_TYPES}
        if not isinstance(value, list):
            raise serializers.ValidationError('Must be a list.')
        invalid = [item for item in value if item not in valid]
        if invalid:
            raise serializers.ValidationError(f'Invalid notification type(s): {", ".join(invalid)}')
        return value
