import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Workspace(models.Model):
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('trial', 'Trial'),
        ('paid', 'Paid'),
    ]
    SUBSCRIPTION_STATUS_CHOICES = [
        ('active', 'Active'),
        ('trialing', 'Trialing'),
        ('past_due', 'Past due'),
        ('canceled', 'Canceled'),
    ]
    PLAN_LIMITS = {
        'free': {'seats': 5, 'projects': 3},
        'trial': {'seats': 10, 'projects': 10},
        'paid': {'seats': 100, 'projects': 100},
    }
    PERMISSION_MODULES = (
        'users', 'clients', 'projects', 'issues', 'tasks', 'reports', 'activity', 'settings',
    )
    DEFAULT_ROLE_PERMISSIONS = {
        'manager': {
            'users': True, 'clients': True, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': True, 'settings': False,
        },
        'client': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': False, 'reports': True, 'activity': False, 'settings': False,
        },
        'frontend_developer': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
        'backend_developer': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
        'fullstack_developer': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
        'devops': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
        'qa_tester': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
        'ui_ux_designer': {
            'users': False, 'clients': False, 'projects': True, 'issues': True,
            'tasks': True, 'reports': True, 'activity': False, 'settings': False,
        },
    }

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    owner = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_workspaces'
    )
    plan = models.CharField(max_length=12, choices=PLAN_CHOICES, default='free')
    subscription_status = models.CharField(
        max_length=12, choices=SUBSCRIPTION_STATUS_CHOICES, default='active'
    )
    billing_email = models.EmailField(blank=True, default='')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    billing_customer_id = models.CharField(max_length=255, blank=True, default='')
    billing_subscription_id = models.CharField(max_length=255, blank=True, default='')
    role_permissions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    @property
    def effective_plan(self):
        if (
            self.plan == 'trial'
            and self.subscription_status == 'trialing'
            and self.trial_ends_at
            and self.trial_ends_at <= timezone.now()
        ):
            return 'free'
        return self.plan

    @property
    def seat_limit(self):
        return self.PLAN_LIMITS[self.effective_plan]['seats']

    @property
    def project_limit(self):
        return self.PLAN_LIMITS[self.effective_plan]['projects']

    def permissions_for_role(self, role):
        if role == 'admin':
            return {module: True for module in self.PERMISSION_MODULES}
        permissions = dict(self.DEFAULT_ROLE_PERMISSIONS.get(role, {}))
        permissions.update(self.role_permissions.get(role, {}))
        return permissions

    def __str__(self):
        return self.name


class User(AbstractUser):
    INVITE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('accepted', 'Accepted'),
    ]
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('frontend_developer', 'Frontend Developer'),
        ('backend_developer', 'Backend Developer'),
        ('fullstack_developer', 'Fullstack Developer'),
        ('devops', 'DevOps Engineer'),
        ('qa_tester', 'QA Tester'),
        ('ui_ux_designer', 'UI/UX Designer'),
        ('client', 'Client'),
    ]
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='frontend_developer')
    invite_status = models.CharField(max_length=20, choices=INVITE_STATUS_CHOICES, default='pending')
    invite_sent_at = models.DateTimeField(null=True, blank=True)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, null=True, blank=True, related_name='users'
    )
    invited_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invited_users',
    )

    def save(self, *args, **kwargs):
        if not self.workspace_id:
            self.workspace = Workspace.objects.order_by('id').first()
        super().save(*args, **kwargs)

    def has_workspace_permission(self, module):
        if self.role == 'admin':
            return True
        if not self.workspace_id or module not in Workspace.PERMISSION_MODULES:
            return False
        return self.workspace.permissions_for_role(self.role).get(module, False)

    def __str__(self):
        return f"{self.username} ({self.role})"


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return (timezone.now() - self.created_at).total_seconds() > 1800  # 30 min

    def __str__(self):
        return f"Reset token for {self.user.username}"
