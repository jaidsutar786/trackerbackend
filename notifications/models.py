from django.db import models
from accounts.models import User
from projects.models import Feature, Issue, Project, Task, SubTask


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('issue_created',       'Issue Created'),
        ('issue_assigned',      'Issue Assigned'),
        ('issue_status_changed','Issue Status Changed'),
        ('issue_comment',       'Issue Comment'),
        ('project_assigned',    'Project Assigned'),
        ('feature_assigned',    'Feature Assigned'),
        ('task_assigned',       'Task Assigned'),
        ('task_completed',      'Task Completed'),
        ('task_status_changed', 'Task Status Changed'),
        ('subtask_assigned',    'SubTask Assigned'),
        ('subtask_status_changed', 'SubTask Status Changed'),
    ]

    recipient         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    actor             = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    title             = models.CharField(max_length=255)
    message           = models.TextField()
    icon              = models.CharField(max_length=10, default='📢')
    read              = models.BooleanField(default=False)
    issue             = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    project           = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    feature           = models.ForeignKey(Feature, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    task              = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    subtask           = models.ForeignKey(SubTask, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read', 'created_at']),
            models.Index(fields=['recipient', 'notification_type']),
            models.Index(fields=['project', 'created_at']),
            models.Index(fields=['issue']),
            models.Index(fields=['feature']),
            models.Index(fields=['task']),
            models.Index(fields=['subtask']),
        ]

    def __str__(self):
        return f'{self.recipient.username} - {self.title}'


class NotificationPreference(models.Model):
    DIGEST_CHOICES = [
        ('off', 'Off'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preference')
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    email_digest = models.CharField(max_length=10, choices=DIGEST_CHOICES, default='off')
    daily_digest_sent_at = models.DateTimeField(null=True, blank=True)
    weekly_digest_sent_at = models.DateTimeField(null=True, blank=True)
    daily_digest_last_notification_id = models.PositiveBigIntegerField(default=0)
    weekly_digest_last_notification_id = models.PositiveBigIntegerField(default=0)
    enabled_types = models.JSONField(default=list, blank=True)
    muted_types = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'email_digest']),
        ]

    def allows(self, notification_type):
        if self.enabled_types and notification_type not in self.enabled_types:
            return False
        if notification_type in self.muted_types:
            return False
        return self.in_app_enabled or (
            self.email_enabled and self.email_digest != 'off'
        )

    def __str__(self):
        return f'{self.user.username} notification preferences'
