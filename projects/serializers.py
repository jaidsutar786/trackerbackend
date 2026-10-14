from rest_framework import serializers
from django.db.models import Count, Q
from accounts.serializers import UserSerializer
from accounts.models import User
from .models import Client, Project, ProjectMilestone, ProjectMember, Issue, IssueComment, IssueScreenshot, ActivityLog, Feature, Task, TaskComment, TaskCommentAttachment, Module, SubTask, SubTaskComment, SubTaskCommentAttachment


def normalize_labels(value):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        labels = [label.strip() for label in value.split(',')]
    elif isinstance(value, list):
        labels = [str(label).strip() for label in value]
    else:
        raise serializers.ValidationError('Labels must be a list or comma-separated string.')
    return [label for label in labels if label][:20]


class ClientSerializer(serializers.ModelSerializer):
    created_by     = UserSerializer(read_only=True)
    project_count  = serializers.SerializerMethodField()
    users          = UserSerializer(many=True, read_only=True)
    user_ids       = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.filter(role='client'),
        source='users',
        write_only=True,
        required=False,
    )

    class Meta:
        model  = Client
        fields = [
            'id', 'name', 'contact_person', 'email', 'phone', 'address',
            'users', 'user_ids', 'created_by', 'project_count', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        users = attrs.get('users')
        request = self.context.get('request')
        workspace_id = self.instance.workspace_id if self.instance else getattr(request.user, 'workspace_id', None)
        if users is not None and any(user.workspace_id != workspace_id for user in users):
            raise serializers.ValidationError({'user_ids': 'Client login users must belong to this workspace.'})
        return attrs

    def get_project_count(self, obj):
        annotated_count = getattr(obj, '_workspace_project_count', None)
        if annotated_count is not None:
            return annotated_count
        return obj.projects.count()

    def create(self, validated_data):
        users = validated_data.pop('users', [])
        client = Client.objects.create(**validated_data)
        client.users.set(users)
        return client

    def update(self, instance, validated_data):
        users = validated_data.pop('users', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if users is not None:
            instance.users.set(users)
        return instance


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        write_only=True, queryset=User.objects.all(), source='user'
    )

    class Meta:
        model = ProjectMember
        fields = ['id', 'user', 'user_id', 'project_role']


class ProjectMilestoneSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectMilestone
        fields = ['id', 'title', 'due_date', 'status', 'status_display', 'notes', 'created_at', 'updated_at']


class ProjectSerializer(serializers.ModelSerializer):
    team_members = ProjectMemberSerializer(many=True, read_only=True)
    created_by   = UserSerializer(read_only=True)
    client       = ClientSerializer(read_only=True)
    client_id    = serializers.IntegerField(source='client.id', read_only=True)
    members      = serializers.SerializerMethodField()
    progress     = serializers.SerializerMethodField()
    feature_count = serializers.SerializerMethodField()
    task_count    = serializers.SerializerMethodField()
    module_count  = serializers.SerializerMethodField()
    milestones    = ProjectMilestoneSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    risk_display   = serializers.CharField(source='get_risk_display', read_only=True)

    class Meta:
        model  = Project
        fields = [
            'id', 'client', 'client_id', 'name', 'description', 'project_key', 'slug',
            'status', 'status_display', 'risk', 'risk_display', 'blockers', 'health_summary',
            'start_date', 'end_date', 'team_members', 'members', 'milestones',
            'created_by', 'created_at', 'updated_at',
            'progress', 'feature_count', 'task_count', 'module_count',
        ]

    def get_members(self, obj):
        return [UserSerializer(tm.user).data for tm in obj.team_members.all()]

    def get_progress(self, obj):
        total = getattr(obj, '_analytics_task_count', None)
        if total is None:
            total = obj.tasks.count()
        if total == 0:
            return 0
        done = getattr(obj, '_analytics_completed_task_count', None)
        if done is None:
            done = obj.tasks.filter(status='Done').count()
        return round((done / total) * 100)

    def get_feature_count(self, obj):
        annotated_count = getattr(obj, '_analytics_feature_count', None)
        if annotated_count is not None:
            return annotated_count
        return obj.features.count()

    def get_task_count(self, obj):
        annotated_count = getattr(obj, '_analytics_task_count', None)
        if annotated_count is not None:
            return annotated_count
        return obj.tasks.count()

    def get_module_count(self, obj):
        annotated_count = getattr(obj, '_analytics_module_count', None)
        if annotated_count is not None:
            return annotated_count
        return obj.modules.count()


def annotate_project_counts(queryset):
    return queryset.annotate(
        _analytics_task_count=Count('tasks', distinct=True),
        _analytics_completed_task_count=Count(
            'tasks', filter=Q(tasks__status='Done'), distinct=True
        ),
        _analytics_feature_count=Count('features', distinct=True),
        _analytics_module_count=Count('modules', distinct=True),
    )


class ProjectWriteSerializer(serializers.ModelSerializer):
    """Used for create/update — accepts team as list of {user_id, project_role, specialization}"""
    team = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    milestones = ProjectMilestoneSerializer(many=True, required=False)

    class Meta:
        model  = Project
        fields = [
            'client', 'name', 'description', 'project_key', 'slug',
            'status', 'risk', 'blockers', 'health_summary',
            'start_date', 'end_date', 'team', 'milestones',
        ]

    def validate(self, attrs):
        start_date = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'End date cannot be before start date.'})
        request = self.context.get('request')
        workspace_id = self.instance.workspace_id if self.instance else getattr(request.user, 'workspace_id', None)
        client = attrs.get('client', getattr(self.instance, 'client', None))
        if client and client.workspace_id != workspace_id:
            raise serializers.ValidationError({'client': 'Choose a client from this workspace.'})
        team = attrs.get('team', [])
        user_ids = [entry.get('user_id') for entry in team if entry.get('user_id')]
        if user_ids and User.objects.filter(pk__in=user_ids, workspace_id=workspace_id).count() != len(set(user_ids)):
            raise serializers.ValidationError({'team': 'Project members must belong to this workspace.'})
        return attrs

    def _sync_team(self, project, team_data):
        project.team_members.all().delete()
        for entry in team_data:
            user_id = entry.get('user_id')
            role    = entry.get('project_role', '')
            if user_id and role:
                try:
                    user = User.objects.get(pk=user_id)
                    ProjectMember.objects.create(
                        project=project, user=user, project_role=role
                    )
                except User.DoesNotExist:
                    pass

    def _sync_milestones(self, project, milestones_data):
        project.milestones.all().delete()
        for entry in milestones_data:
            title = (entry.get('title') or '').strip()
            if not title:
                continue
            ProjectMilestone.objects.create(
                project=project,
                title=title,
                due_date=entry.get('due_date') or None,
                status=entry.get('status') or 'planned',
                notes=entry.get('notes') or '',
            )

    def create(self, validated_data):
        team_data = validated_data.pop('team', [])
        milestones_data = validated_data.pop('milestones', [])
        project   = Project.objects.create(**validated_data)
        self._sync_team(project, team_data)
        self._sync_milestones(project, milestones_data)
        return project

    def update(self, instance, validated_data):
        team_data = validated_data.pop('team', None)
        milestones_data = validated_data.pop('milestones', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if team_data is not None:
            self._sync_team(instance, team_data)
        if milestones_data is not None:
            self._sync_milestones(instance, milestones_data)
        return instance


class IssueCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    parent_id = serializers.IntegerField(source='parent.id', read_only=True, allow_null=True)
    replies = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    uploaded_screenshots = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = IssueComment
        fields = ['id', 'author', 'text', 'parent_id', 'replies', 'attachments', 'uploaded_screenshots', 'likes_count', 'user_has_liked', 'created_at']

    def get_replies(self, obj):
        # Only include replies if this is a top-level comment
        if obj.parent is None:
            replies = obj.replies.all()
            return IssueCommentSerializer(replies, many=True, context=self.context).data
        return []
    
    def get_user_has_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(id=request.user.id).exists()
        return False

    def get_attachments(self, obj):
        request = self.context.get('request')
        attachments = []
        for screenshot in obj.comment_screenshots.all():
            url = screenshot.image.url
            if request:
                url = request.build_absolute_uri(url)
            attachments.append({
                'id': screenshot.id,
                'url': url,
                'uploaded_at': screenshot.uploaded_at,
            })
        return attachments

    def get_uploaded_screenshots(self, obj):
        return self.get_attachments(obj)


class IssueScreenshotSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = IssueScreenshot
        fields = ['id', 'url', 'uploaded_at']

    def get_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class IssueSerializer(serializers.ModelSerializer):
    reported_by    = UserSerializer(read_only=True)
    assignee       = UserSerializer(read_only=True)
    comments       = IssueCommentSerializer(many=True, read_only=True)
    screenshots    = IssueScreenshotSerializer(many=True, read_only=True)
    project_name   = serializers.CharField(source='project.name', read_only=True)
    screenshot_url = serializers.SerializerMethodField()  # legacy

    class Meta:
        model = Issue
        fields = [
            'id', 'project', 'project_name', 'title', 'description', 'issue_type',
            'priority', 'status', 'screenshot', 'screenshot_url', 'screenshots',
            'reported_by', 'assignee', 'comments', 'created_at', 'updated_at'
        ]

    def get_screenshot_url(self, obj):
        if obj.screenshot:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.screenshot.url)
        return None


class IssueWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Issue
        fields = ['project', 'title', 'description', 'issue_type', 'priority', 'status', 'assignee', 'screenshot']


class ModuleSerializer(serializers.ModelSerializer):
    created_by    = UserSerializer(read_only=True)
    owner         = UserSerializer(read_only=True)
    feature_count = serializers.SerializerMethodField()
    task_count    = serializers.SerializerMethodField()
    total_task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()
    progress      = serializers.IntegerField(read_only=True)
    has_features  = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = Module
        fields = [
            'id', 'project', 'title', 'module_id',
            'owner', 'status', 'status_display', 'health_summary',
            'created_by', 'feature_count', 'task_count', 'total_task_count',
            'completed_task_count', 'progress', 'has_features',
            'created_at', 'updated_at',
        ]

    def get_feature_count(self, obj):
        return obj.features.count()

    def get_task_count(self, obj):
        return obj.direct_tasks.count()

    def get_total_task_count(self, obj):
        return Task.objects.filter(Q(module=obj) | Q(feature__module=obj)).distinct().count()

    def get_completed_task_count(self, obj):
        return Task.objects.filter(Q(module=obj) | Q(feature__module=obj), status='Done').distinct().count()

    def get_has_features(self, obj):
        return obj.features.exists()


class ModuleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Module
        fields = ['project', 'title', 'owner', 'status', 'health_summary']

    def validate(self, attrs):
        project = attrs.get('project', getattr(self.instance, 'project', None))
        owner = attrs.get('owner', getattr(self.instance, 'owner', None))
        if owner and project and not project.team_members.filter(user=owner).exists():
            raise serializers.ValidationError({'owner': 'Module owner must be a member of this project.'})
        return attrs


class TaskCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    attachments = serializers.SerializerMethodField()
    uploaded_screenshots = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ['id', 'author', 'text', 'attachments', 'uploaded_screenshots', 'likes_count', 'user_has_liked', 'created_at']

    def get_user_has_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(id=request.user.id).exists()
        return False

    def get_attachments(self, obj):
        request = self.context.get('request')
        attachments = []
        for attachment in obj.attachments.all():
            url = attachment.image.url
            if request:
                url = request.build_absolute_uri(url)
            attachments.append({
                'id': attachment.id,
                'url': url,
                'uploaded_at': attachment.uploaded_at,
            })
        return attachments

    def get_uploaded_screenshots(self, obj):
        return self.get_attachments(obj)


class TaskCommentAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = TaskCommentAttachment
        fields = ['id', 'url', 'uploaded_at']

    def get_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class SubTaskCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    attachments = serializers.SerializerMethodField()
    uploaded_screenshots = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = SubTaskComment
        fields = ['id', 'author', 'text', 'attachments', 'uploaded_screenshots', 'likes_count', 'user_has_liked', 'created_at']

    def get_user_has_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(id=request.user.id).exists()
        return False

    def get_attachments(self, obj):
        request = self.context.get('request')
        attachments = []
        for attachment in obj.attachments.all():
            url = attachment.image.url
            if request:
                url = request.build_absolute_uri(url)
            attachments.append({
                'id': attachment.id,
                'url': url,
                'uploaded_at': attachment.uploaded_at,
            })
        return attachments

    def get_uploaded_screenshots(self, obj):
        return self.get_attachments(obj)


class SubTaskCommentAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = SubTaskCommentAttachment
        fields = ['id', 'url', 'uploaded_at']

    def get_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class SubTaskSerializer(serializers.ModelSerializer):
    assignee   = UserSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    reporter   = UserSerializer(source='created_by', read_only=True)

    class Meta:
        model  = SubTask
        fields = [
            'id', 'subtask_id', 'task', 'title', 'description',
            'status', 'priority', 'assignee', 'due_date', 'blocker_reason', 'created_by', 'reporter',
            'created_at', 'updated_at',
        ]


class SubTaskWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SubTask
        fields = ['title', 'description', 'status', 'priority', 'assignee', 'due_date', 'blocker_reason']

    def validate(self, attrs):
        task = self.context.get('task') or getattr(self.instance, 'task', None)
        assignee = attrs.get('assignee', getattr(self.instance, 'assignee', None))
        if task and assignee and not task.project.team_members.filter(user=assignee).exists():
            raise serializers.ValidationError({'assignee': 'Assignee must be a member of this project.'})
        return attrs


class TaskSerializer(serializers.ModelSerializer):
    assignee = UserSerializer(read_only=True)
    reporter = UserSerializer(read_only=True)
    comments = TaskCommentSerializer(many=True, read_only=True)
    subtasks = SubTaskSerializer(many=True, read_only=True)
    project_name  = serializers.CharField(source='project.name', read_only=True)
    module_title  = serializers.CharField(source='module.title', read_only=True, default=None)
    feature_title = serializers.CharField(source='feature.title', read_only=True, default=None)
    feature_key   = serializers.CharField(source='feature.feature_id', read_only=True, default=None)
    subtask_count = serializers.SerializerMethodField()
    completed_subtask_count = serializers.SerializerMethodField()
    subtask_progress = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'id', 'task_id', 'feature', 'module', 'project', 'project_name',
            'module_title', 'feature_title', 'feature_key',
            'title', 'description',
            'status', 'priority', 'assignee', 'reporter', 'due_date',
            'estimate_hours', 'blocker_reason', 'labels',
            'started_at', 'completed_at', 'subtask_count', 'completed_subtask_count', 'subtask_progress',
            'subtasks', 'comments', 'created_at', 'updated_at',
        ]

    def get_subtask_count(self, obj):
        return obj.subtasks.count()

    def get_completed_subtask_count(self, obj):
        return obj.subtasks.filter(status='Done').count()

    def get_subtask_progress(self, obj):
        total = obj.subtasks.count()
        if total == 0:
            return 0
        return round((obj.subtasks.filter(status='Done').count() / total) * 100)


class TaskWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Task
        fields = [
            'feature', 'module', 'project', 'title', 'description',
            'status', 'priority', 'assignee', 'due_date',
            'estimate_hours', 'blocker_reason', 'labels',
        ]

    def validate(self, attrs):
        project = attrs.get('project', getattr(self.instance, 'project', None))
        assignee = attrs.get('assignee', getattr(self.instance, 'assignee', None))
        if project and assignee and not project.team_members.filter(user=assignee).exists():
            raise serializers.ValidationError({'assignee': 'Assignee must be a member of this project.'})
        estimate = attrs.get('estimate_hours', getattr(self.instance, 'estimate_hours', None))
        if estimate is not None and estimate < 0:
            raise serializers.ValidationError({'estimate_hours': 'Estimate cannot be negative.'})
        if 'labels' in attrs:
            attrs['labels'] = normalize_labels(attrs.get('labels'))
        return attrs


class FeatureSerializer(serializers.ModelSerializer):
    assignee        = UserSerializer(read_only=True)
    reporter        = UserSerializer(read_only=True)
    tasks           = TaskSerializer(many=True, read_only=True)
    progress        = serializers.IntegerField(read_only=True)
    project_members = serializers.SerializerMethodField()
    module_title    = serializers.CharField(source='module.title', read_only=True)
    task_count      = serializers.SerializerMethodField()
    status_display  = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model  = Feature
        fields = [
            'id', 'feature_id', 'project', 'module', 'module_title',
            'title', 'description', 'requirement_type',
            'status', 'status_display', 'priority',
            'priority_display', 'assignee', 'reporter', 'tasks',
            'task_count', 'progress', 'project_members', 'created_at', 'updated_at',
        ]

    def get_project_members(self, obj):
        return [UserSerializer(tm.user).data for tm in obj.project.team_members.all()]

    def get_task_count(self, obj):
        return obj.tasks.count()


class FeatureWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Feature
        fields = [
            'project', 'module', 'title', 'description',
            'requirement_type', 'status', 'priority', 'assignee',
        ]

    def validate(self, attrs):
        project = attrs.get('project', getattr(self.instance, 'project', None))
        assignee = attrs.get('assignee', getattr(self.instance, 'assignee', None))
        if project and assignee and not project.team_members.filter(user=assignee).exists():
            raise serializers.ValidationError({'assignee': 'Assignee must be a member of this project.'})
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    actor_name     = serializers.SerializerMethodField()
    actor_role     = serializers.CharField(source='actor.role', read_only=True, default='')
    actor_initials = serializers.SerializerMethodField()
    project_id     = serializers.SerializerMethodField()
    project_name   = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model  = ActivityLog
        fields = ['id', 'actor_name', 'actor_role', 'actor_initials', 'action', 'target', 'project_id', 'project_name', 'extra', 'created_at']

    def get_actor_name(self, obj):
        if not obj.actor:
            return '?'
        return obj.actor.get_full_name() or obj.actor.username

    def get_actor_initials(self, obj):
        if not obj.actor:
            return '?'
        name = obj.actor.get_full_name() or obj.actor.username
        parts = name.split()
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else name[:2].upper()

    def get_project_id(self, obj):
        return obj.project_id
