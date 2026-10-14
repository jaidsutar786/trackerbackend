from django.db import models
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from accounts.models import User, Workspace


def _project_code(project):
    return (project.project_key or slugify(project.name).upper()[:6] or 'PRJ').upper()


def _module_code_from_slug(module):
    if not module or not module.module_id:
        return ''
    parts = module.module_id.split('-')
    if len(parts) >= 2 and parts[1].upper().startswith('M') and parts[1][1:].isdigit():
        return parts[1].upper()
    return ''


class Client(models.Model):
    workspace        = models.ForeignKey(Workspace, on_delete=models.PROTECT, null=True, blank=True, related_name='clients')
    name            = models.CharField(max_length=255)
    contact_person  = models.CharField(max_length=255, blank=True, default='')
    email           = models.EmailField(blank=True, default='')
    phone           = models.CharField(max_length=50, blank=True, default='')
    address         = models.TextField(blank=True, default='')
    users           = models.ManyToManyField(User, blank=True, related_name='client_companies')
    created_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_clients')
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.created_by_id:
            self.workspace_id = self.created_by.workspace_id
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Project(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    RISK_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    workspace   = models.ForeignKey(Workspace, on_delete=models.PROTECT, null=True, blank=True, related_name='projects')
    client      = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    name        = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    project_key = models.CharField(max_length=10, unique=True, blank=True, default='')
    slug        = models.SlugField(max_length=255, blank=True, default='')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    risk        = models.CharField(max_length=20, choices=RISK_CHOICES, default='low')
    blockers    = models.TextField(blank=True, default='')
    health_summary = models.TextField(blank=True, default='')
    start_date  = models.DateField(null=True, blank=True)
    end_date    = models.DateField(null=True, blank=True)
    created_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_projects')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', 'created_at']),
            models.Index(fields=['project_key']),
            models.Index(fields=['slug']),
        ]

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.client_id:
            self.workspace_id = self.client.workspace_id
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.project_key:
            # Auto-generate from name initials e.g. "HR Management" -> "HRM"
            words = self.name.upper().split()
            base_key = ''.join(w[0] for w in words)[:6] if words else 'PRJ'
            candidate = base_key
            suffix = 2
            while Project.objects.exclude(pk=self.pk).filter(project_key=candidate).exists():
                candidate = f'{base_key[: max(1, 10 - len(str(suffix)))]}{suffix}'
                suffix += 1
            self.project_key = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.client.name})'


class ProjectMilestone(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('blocked', 'Blocked'),
    ]

    project     = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='milestones')
    title       = models.CharField(max_length=255)
    due_date    = models.DateField(null=True, blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    notes       = models.TextField(blank=True, default='')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['project', 'due_date']),
        ]

    def __str__(self):
        return f'{self.title} - {self.project.name}'


class ProjectMember(models.Model):
    PROJECT_ROLES = [
        ('manager',   'Manager'),
        ('lead',      'Lead'),
        ('developer', 'Developer'),
        ('tester',    'Tester'),
        ('devops',    'DevOps'),
    ]

    project      = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='team_members')
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_memberships')
    project_role = models.CharField(max_length=20, choices=PROJECT_ROLES)

    class Meta:
        unique_together = ('project', 'user')
        indexes = [
            models.Index(fields=['project', 'project_role']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f'{self.user.username} — {self.project_role} @ {self.project.name}'


class Issue(models.Model):
    ISSUE_TYPES = [
        ('bug', 'Bug'),
        ('story', 'Feature Request'),
        ('task', 'Task'),
    ]
    PRIORITIES = [
        ('highest', 'Highest'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    STATUSES = [
        ('To Do', 'To Do'),
        ('In Progress', 'In Progress'),
        ('Testing', 'Testing'),
        ('Done', 'Done'),
    ]

    project      = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    title        = models.TextField(db_column='title')
    description  = models.TextField()
    issue_type   = models.CharField(max_length=20, choices=ISSUE_TYPES, default='bug')
    priority     = models.CharField(max_length=20, choices=PRIORITIES, default='medium')
    status       = models.CharField(max_length=20, choices=STATUSES, default='To Do')
    screenshot   = models.ImageField(upload_to='issue_screenshots/', blank=True, null=True)  # legacy single
    reported_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reported_issues')
    assignee     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_issues')
    developer    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='developer_issues')  # original developer
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['assignee', 'status']),
            models.Index(fields=['reported_by', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.title} ({self.project.name})'


class IssueScreenshot(models.Model):
    issue       = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='screenshots')
    comment     = models.ForeignKey('IssueComment', on_delete=models.SET_NULL, null=True, blank=True, related_name='comment_screenshots')
    image       = models.ImageField(upload_to='issue_screenshots/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Screenshot for {self.issue.title}'


class IssueComment(models.Model):
    issue      = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE)
    text       = models.TextField()
    parent     = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    likes      = models.ManyToManyField(User, related_name='liked_comments', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author.username} on {self.issue.title}'
    
    @property
    def likes_count(self):
        return self.likes.count()


class Module(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('active', 'Active'),
        ('blocked', 'Blocked'),
        ('done', 'Done'),
    ]

    """Module — functional modules like Admin Login, Client Portal, etc."""

    project     = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='modules')
    title       = models.CharField(max_length=255)
    module_id   = models.CharField(max_length=20, blank=True)  # e.g. YOJAK-M01
    owner       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_modules')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    health_summary = models.TextField(blank=True, default='')
    created_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_modules')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('project', 'module_id')
        indexes = [
            models.Index(fields=['project', 'module_id']),
        ]

    def save(self, *args, **kwargs):
        if not self.module_id:
            module_num = Module.objects.filter(project=self.project).exclude(pk=self.pk).count() + 1
            self.module_id = f'{_project_code(self.project)}-M{module_num:02d}'
        super().save(*args, **kwargs)

    @property
    def module_key(self):
        return self.module_id

    @property
    def progress(self):
        tasks = Task.objects.filter(Q(module=self) | Q(feature__module=self)).distinct()
        total = tasks.count()
        if total == 0:
            return 0
        done = tasks.filter(status='Done').count()
        return round((done / total) * 100)

    def __str__(self):
        return f'{self.module_id}: {self.title}'


class Feature(models.Model):
    """Feature — sits above Tasks inside a Module"""
    STATUSES = [
        ('To Do',       'To Do'),
        ('In Progress', 'In Progress'),
        ('Testing', 'Testing'),
        ('Blocked',     'Blocked'),
        ('Done',        'Done'),
    ]
    PRIORITIES = [
        ('highest', 'Highest'),
        ('high',    'High'),
        ('medium',  'Medium'),
        ('low',     'Low'),
        ('lowest',  'Lowest'),
    ]
    project     = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='features')
    module      = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='features', null=True, blank=True)
    feature_id  = models.CharField(max_length=20, blank=True)   # e.g. HRM-1
    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    requirement_type = models.CharField(max_length=255, blank=True, default='')
    status      = models.CharField(max_length=20, choices=STATUSES, default='To Do')
    priority    = models.CharField(max_length=20, choices=PRIORITIES, default='medium')
    assignee    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_features')
    reporter    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reported_features')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['feature_id']
        constraints = [
            models.UniqueConstraint(fields=['project', 'feature_id'], name='unique_feature_id_per_project'),
        ]
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['module', 'status']),
            models.Index(fields=['assignee', 'status']),
            models.Index(fields=['feature_id']),
        ]

    def save(self, *args, **kwargs):
        if not self.feature_id:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project_id)
                if self.module:
                    # Module-based numbering: e.g. HRM-M01-F01
                    last = Feature.objects.filter(module=self.module).order_by('-id').first()
                    num = 1
                    if last and last.feature_id:
                        try:
                            last_part = last.feature_id.split('-')[-1].upper().replace('F', '')
                            num = int(last_part) + 1
                        except ValueError:
                            num = Feature.objects.filter(module=self.module).count() + 1
                    module_code = _module_code_from_slug(self.module) or f'M{self.module_id:02d}'
                    self.feature_id = f'{_project_code(self.project)}-{module_code}-F{num:02d}'
                else:
                    # Project-based numbering (no module): e.g. HRM-F01
                    last = Feature.objects.filter(project=self.project, module__isnull=True).order_by('-id').first()
                    num = 1
                    if last and last.feature_id:
                        try:
                            last_part = last.feature_id.split('-')[-1].upper().replace('F', '')
                            num = int(last_part) + 1
                        except ValueError:
                            num = Feature.objects.filter(project=self.project, module__isnull=True).count() + 1
                    self.feature_id = f'{_project_code(self.project)}-F{num:02d}'
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.feature_id}: {self.title}'

    @property
    def progress(self):
        total = self.tasks.count()
        if total == 0:
            return 0
        done = self.tasks.filter(status='Done').count()
        return round((done / total) * 100)


class Task(models.Model):
    """Task inside a Feature or directly in Module (if no features) - Simplified"""
    STATUSES = [
        ('To Do',       'To Do'),
        ('In Progress', 'In Progress'),
        ('Testing',     'Testing'),
        ('Blocked',     'Blocked'),
        ('Done',        'Done'),
    ]
    PRIORITIES = [
        ('highest', 'Highest'),
        ('high',    'High'),
        ('medium',  'Medium'),
        ('low',     'Low'),
        ('lowest',  'Lowest'),
    ]

    # Relationships
    feature     = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name='tasks', null=True, blank=True)
    module      = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='direct_tasks', null=True, blank=True)
    project     = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    task_id     = models.CharField(max_length=20, blank=True)   # e.g. WRK-5
    
    # Basic Info
    title       = models.TextField()
    description = models.TextField(blank=True, default='')
    
    # Status & Priority
    status      = models.CharField(max_length=20, choices=STATUSES, default='To Do')
    priority    = models.CharField(max_length=20, choices=PRIORITIES, default='medium')
    
    # Assignment
    assignee    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    reporter    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reported_tasks')
    developer   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='developer_tasks')  # original developer before testing
    
    # Delivery metadata
    due_date       = models.DateField(null=True, blank=True)
    estimate_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    blocker_reason = models.TextField(blank=True, default='')
    labels         = models.JSONField(default=list, blank=True)
    started_at     = models.DateTimeField(null=True, blank=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['project', 'task_id'], name='unique_task_id_per_project'),
        ]
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['feature', 'status']),
            models.Index(fields=['module', 'status']),
            models.Index(fields=['assignee', 'status']),
            models.Index(fields=['task_id']),
            models.Index(fields=['due_date']),
            models.Index(fields=['priority', 'status']),
        ]

    def save(self, *args, **kwargs):
        previous_status = None
        if self.pk:
            previous_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()

        lifecycle_fields = set()
        if self.status == 'In Progress' and self.started_at is None:
            self.started_at = timezone.now()
            lifecycle_fields.add('started_at')
        if self.status == 'Done' and self.completed_at is None:
            self.completed_at = timezone.now()
            lifecycle_fields.add('completed_at')
        elif previous_status == 'Done' and self.status != 'Done' and self.completed_at is not None:
            self.completed_at = None
            lifecycle_fields.add('completed_at')

        if kwargs.get('update_fields') is not None and lifecycle_fields:
            kwargs['update_fields'] = set(kwargs['update_fields']) | lifecycle_fields

        if not self.task_id:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project_id)
                last = Task.objects.filter(project=self.project).exclude(pk=self.pk).order_by('-id').first()
                num = 1
                if last and last.task_id:
                    try:
                        num = int(last.task_id.split('-')[-1]) + 1
                    except ValueError:
                        num = Task.objects.filter(project=self.project).exclude(pk=self.pk).count() + 1
                self.task_id = f'{self.project.project_key}-{num}'
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.task_id}: {self.title}'


class TaskComment(models.Model):
    task       = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE)
    text       = models.TextField()
    likes      = models.ManyToManyField(User, related_name='liked_task_comments', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author.username} on {self.task.title}'
    
    @property
    def likes_count(self):
        return self.likes.count()


class TaskCommentAttachment(models.Model):
    comment     = models.ForeignKey(TaskComment, on_delete=models.CASCADE, related_name='attachments')
    image       = models.ImageField(upload_to='task_comment_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Attachment for comment {self.comment_id}'


class SubTask(models.Model):
    """SubTask inside a Task — for splitting work between Frontend/Backend/etc."""
    STATUSES = [
        ('To Do',       'To Do'),
        ('In Progress', 'In Progress'),
        ('Testing',     'Testing'),
        ('Blocked',     'Blocked'),
        ('Done',        'Done'),
    ]
    PRIORITIES = [
        ('highest', 'Highest'),
        ('high',    'High'),
        ('medium',  'Medium'),
        ('low',     'Low'),
        ('lowest',  'Lowest'),
    ]

    task        = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='subtasks')
    subtask_id  = models.CharField(max_length=30, blank=True)  # e.g. YOJAK-1-S1
    title       = models.CharField(max_length=500)
    description = models.TextField(blank=True, default='')
    status      = models.CharField(max_length=20, choices=STATUSES, default='To Do')
    priority    = models.CharField(max_length=20, choices=PRIORITIES, default='medium')
    assignee    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_subtasks')
    created_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_subtasks')
    due_date    = models.DateField(null=True, blank=True)
    blocker_reason = models.TextField(blank=True, default='')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['task', 'subtask_id'], name='unique_subtask_id_per_task'),
        ]
        indexes = [
            models.Index(fields=['task', 'subtask_id']),
            models.Index(fields=['due_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.subtask_id:
            with transaction.atomic():
                parent = Task.objects.select_for_update().get(pk=self.task_id)
                last = SubTask.objects.filter(task=parent).exclude(pk=self.pk).order_by('-id').first()
                num = 1
                if last and last.subtask_id:
                    try:
                        num = int(last.subtask_id.split('-S')[-1]) + 1
                    except ValueError:
                        num = SubTask.objects.filter(task=parent).exclude(pk=self.pk).count() + 1
                self.subtask_id = f'{parent.task_id}-S{num}'
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.subtask_id}: {self.title}'


class SubTaskComment(models.Model):
    subtask    = models.ForeignKey(SubTask, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE)
    text       = models.TextField()
    likes      = models.ManyToManyField(User, related_name='liked_subtask_comments', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author.username} on {self.subtask.title}'
    
    @property
    def likes_count(self):
        return self.likes.count()


class SubTaskCommentAttachment(models.Model):
    comment     = models.ForeignKey(SubTaskComment, on_delete=models.CASCADE, related_name='attachments')
    image       = models.ImageField(upload_to='subtask_comment_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Attachment for subtask comment {self.comment_id}'


class ActivityLog(models.Model):
    ACTION_TYPES = [
        ('issue_created',    'Issue Created'),
        ('issue_updated',    'Issue Updated'),
        ('issue_deleted',    'Issue Deleted'),
        ('status_changed',   'Status Changed'),
        ('comment_added',    'Comment Added'),
        ('project_created',  'Project Created'),
        ('project_updated',  'Project Updated'),
        ('module_created',   'Module Created'),
        ('module_updated',   'Module Updated'),
        ('module_deleted',   'Module Deleted'),
        ('feature_created',  'Feature Created'),
        ('feature_updated',  'Feature Updated'),
        ('feature_deleted',  'Feature Deleted'),
        ('task_created',     'Task Created'),
        ('task_updated',     'Task Updated'),
        ('task_deleted',     'Task Deleted'),
        ('subtask_created',  'Subtask Created'),
        ('subtask_updated',  'Subtask Updated'),
        ('subtask_deleted',  'Subtask Deleted'),
        ('user_invited',     'User Invited'),
        ('invite_resent',    'Invite Resent'),
        ('user_updated',     'User Updated'),
        ('role_changed',     'Role Changed'),
        ('user_disabled',    'User Disabled'),
        ('user_deleted',     'User Deleted'),
        ('client_created',   'Client Created'),
        ('client_updated',   'Client Updated'),
        ('client_deleted',   'Client Deleted'),
        ('assignee_changed', 'Assignee Changed'),
    ]

    actor      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='activity_logs')
    action     = models.CharField(max_length=30, choices=ACTION_TYPES)
    target     = models.CharField(max_length=255)   # human-readable target name
    project    = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    issue      = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True, blank=True)
    extra      = models.JSONField(default=dict, blank=True)  # e.g. old/new status
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.actor} — {self.action} — {self.target}'
