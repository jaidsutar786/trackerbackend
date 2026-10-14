import secrets
import string
import logging
from django.contrib.auth import authenticate
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from core.permissions import WorkspaceModuleAccess

from .models import User, PasswordResetToken
from .serializers import LoginSerializer, UserSerializer, CreateUserSerializer, UpdateUserSerializer, WorkspaceSerializer
from projects.models import Project, ProjectMember, Issue, Task, ActivityLog

logger = logging.getLogger(__name__)


def log_user_activity(actor, action, target_user, extra=None):
    ActivityLog.objects.create(
        actor=actor,
        action=action,
        target=target_user.get_full_name() or target_user.username,
        extra={
            'user_id': target_user.id,
            'email': target_user.email,
            'role': target_user.role,
            **(extra or {}),
        },
    )


class IsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == 'admin'


def generate_password(length=10):
    chars = string.ascii_letters + string.digits + '!@#$'
    return ''.join(secrets.choice(chars) for _ in range(length))


def send_welcome_email(user, plain_password):
    if not user.email:
        raise ValueError('User email is required to send an invite.')
    if not settings.DEFAULT_FROM_EMAIL:
        raise ImproperlyConfigured('DEFAULT_FROM_EMAIL is not configured.')

    role_display = user.role.capitalize()
    login_url = settings.FRONTEND_URL.rstrip('/') + '/login'
    name = user.first_name or user.username

    subject = f'Welcome to Teople — Your {role_display} Account'
    message = f"""Hi {name},

Your Teople account has been created by the admin.

Here are your login credentials:

  Email / Username : {user.username}
  Password         : {plain_password}
  Role             : {role_display}

Login here: {login_url}

Please change your password after first login.

— Teople Team
"""
    sent_count = send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError(f'Invite email was not accepted by the email backend for {user.email}.')
    user.invite_status = 'sent'
    user.invite_sent_at = timezone.now()
    user.save(update_fields=['invite_status', 'invite_sent_at'])
    logger.info(
        'Invite email sent successfully',
        extra={'user_id': user.id, 'email': user.email, 'role': user.role},
    )
    return sent_count


class LoginView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        user = authenticate(username=username, password=password)
        if not user:
            inactive_user = User.objects.filter(username=username, is_active=False).first()
            if inactive_user and inactive_user.check_password(password):
                return Response({'error': 'Your account is deactivated. Please contact admin.'}, status=status.HTTP_403_FORBIDDEN)
            inactive_user = User.objects.filter(email__iexact=username, is_active=False).first()
            if inactive_user and inactive_user.check_password(password):
                return Response({'error': 'Your account is deactivated. Please contact admin.'}, status=status.HTTP_403_FORBIDDEN)
        if not user:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_active:
            return Response({'error': 'Your account is deactivated. Please contact admin.'}, status=status.HTTP_403_FORBIDDEN)
        if user.invite_status != 'accepted':
            user.invite_status = 'accepted'
            user.save(update_fields=['invite_status'])
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class WorkspaceSettingsView(APIView):
    workspace_module = 'settings'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        if not request.user.workspace_id:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        return Response(WorkspaceSerializer(request.user.workspace).data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'Only workspace admins can update settings.'}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.workspace_id:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        serializer = WorkspaceSerializer(request.user.workspace, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save()
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceUsageView(APIView):
    workspace_module = 'settings'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        workspace = request.user.workspace
        if not workspace:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        active_seats = workspace.users.filter(is_active=True).count()
        project_count = workspace.projects.count()
        effective_plan = workspace.effective_plan
        return Response({
            'plan': effective_plan,
            'subscription_status': (
                'canceled'
                if workspace.plan == 'trial' and effective_plan == 'free'
                else workspace.subscription_status
            ),
            'seats': {'used': active_seats, 'limit': workspace.seat_limit},
            'projects': {'used': project_count, 'limit': workspace.project_limit},
            'can_add_seat': active_seats < workspace.seat_limit,
            'can_add_project': project_count < workspace.project_limit,
        })


class UserListCreateView(APIView):
    workspace_module = 'users'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        # Manager can view users, but only admin can create
        role = request.query_params.get('role')
        users = User.objects.filter(workspace=request.user.workspace).exclude(id=request.user.id)
        if role:
            users = users.filter(role=role)
        return Response(UserSerializer(users, many=True).data)

    def post(self, request):
        # Only admin can create users
        if request.user.role != 'admin':
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        workspace = request.user.workspace
        if not workspace:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        # Auto-generate password if not provided
        data = request.data.copy()
        plain_password = data.get('password') or generate_password()
        data['password'] = plain_password

        # Auto-generate username from email if not provided
        if not data.get('username') and data.get('email'):
            base = data['email'].split('@')[0]
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{base}{counter}'
                counter += 1
            data['username'] = username

        serializer = CreateUserSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                workspace = type(workspace).objects.select_for_update().get(pk=workspace.pk)
                active_seats = workspace.users.filter(is_active=True).count()
                if active_seats >= workspace.seat_limit:
                    return Response({
                        'error': f'This workspace has reached its {workspace.seat_limit}-seat {workspace.effective_plan} plan limit.',
                        'usage': {'used': active_seats, 'limit': workspace.seat_limit},
                    }, status=status.HTTP_409_CONFLICT)
                user = serializer.save(workspace=workspace)
                user.invited_by = request.user
                user.invite_status = 'pending'
                user.save(update_fields=['invited_by', 'invite_status'])
                send_welcome_email(user, plain_password)
                log_user_activity(request.user, 'user_invited', user)
        except Exception:
            logger.exception(
                'Invite failed; user was not created',
                extra={'email': data.get('email'), 'role': data.get('role')},
            )
            return Response(
                {'error': 'Invite email could not be sent. Please check email settings and try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_data = UserSerializer(user).data
        response_data['invite_email_sent'] = True
        return Response(response_data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    workspace_module = 'users'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, pk, workspace):
        try:
            return User.objects.get(pk=pk, workspace=workspace)
        except User.DoesNotExist:
            return None

    def get(self, request, pk):
        user = self.get_object(pk, request.user.workspace)
        if not user:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object(pk, request.user.workspace)
        if not user:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = UpdateUserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_role = user.role
        was_active = user.is_active
        updated_user = serializer.save()

        # Agar system role change hua toh project_role bhi sync karo
        new_role = request.data.get('role')
        if new_role:
            SYSTEM_TO_PROJECT_ROLE = {
                'manager':             'manager',
                'frontend_developer':  'developer',
                'backend_developer':   'developer',
                'fullstack_developer': 'developer',
                'qa_tester':           'tester',
                'devops':              'devops',
                'ui_ux_designer':      'developer',
            }
            project_role = SYSTEM_TO_PROJECT_ROLE.get(new_role)
            if project_role:
                from projects.models import ProjectMember
                ProjectMember.objects.filter(user=updated_user).update(project_role=project_role)

        if old_role != updated_user.role:
            log_user_activity(request.user, 'role_changed', updated_user, extra={'from': old_role, 'to': updated_user.role})
        elif was_active and not updated_user.is_active:
            log_user_activity(request.user, 'user_disabled', updated_user)
        else:
            log_user_activity(request.user, 'user_updated', updated_user)

        return Response(UserSerializer(updated_user).data)

    def delete(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object(pk, request.user.workspace)
        if not user:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        log_user_activity(request.user, 'user_deleted', user)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResendInviteView(APIView):
    workspace_module = 'users'
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        user = User.objects.filter(pk=pk, workspace=request.user.workspace).first()
        if not user:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user.email:
            return Response({'error': 'User does not have an email address.'}, status=status.HTTP_400_BAD_REQUEST)

        plain_password = generate_password()
        try:
            with transaction.atomic():
                user.set_password(plain_password)
                user.invited_by = request.user
                user.invite_status = 'pending'
                user.save(update_fields=['password', 'invited_by', 'invite_status'])
                send_welcome_email(user, plain_password)
                log_user_activity(request.user, 'invite_resent', user)
        except Exception:
            logger.exception('Invite resend failed', extra={'user_id': user.id, 'email': user.email})
            return Response(
                {'error': 'Invite email could not be resent. Please check email settings and try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(UserSerializer(user).data)


class UserProfileStatsView(APIView):
    workspace_module = 'users'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, pk):
        target = User.objects.filter(pk=pk, workspace=request.user.workspace).first()
        if not target:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        role = target.role
        data = {}

        if role == 'admin':
            projects = Project.objects.filter(workspace=target.workspace)
            data['stats'] = {
                'total_users':    User.objects.filter(workspace=target.workspace).count(),
                'total_projects': projects.count(),
                'total_issues':   Issue.objects.filter(project__in=projects).count(),
                'open_issues':    Issue.objects.filter(project__in=projects).exclude(status='Done').count(),
            }
            data['recent_activity'] = list(
                ActivityLog.objects.select_related('actor', 'project')
                .filter(Q(project__workspace=target.workspace) | Q(actor__workspace=target.workspace))
                .order_by('-created_at')[:10]
                .values('action', 'target', 'created_at', 'project__name',
                        'actor__username', 'actor__first_name', 'actor__last_name', 'actor__role', 'extra')
            )

        elif role == 'manager':
            projects = Project.objects.filter(workspace=target.workspace, team_members__user=target).distinct()
            data['stats'] = {
                'total_projects': projects.count(),
                'total_issues':   Issue.objects.filter(project__in=projects).count(),
                'open_issues':    Issue.objects.filter(project__in=projects).exclude(status='Done').count(),
                'team_members':   ProjectMember.objects.filter(project__in=projects).values('user').distinct().count(),
            }
            data['projects'] = list(projects.values('id', 'name', 'slug', 'start_date', 'end_date')[:6])
            data['recent_activity'] = list(
                ActivityLog.objects.select_related('actor', 'project')
                .filter(project__in=projects).order_by('-created_at')[:10]
                .values('action', 'target', 'created_at', 'project__name',
                        'actor__username', 'actor__first_name', 'actor__last_name', 'actor__role', 'extra')
            )

        elif role == 'client':
            issues = Issue.objects.filter(reported_by=target)
            projects = Project.objects.filter(workspace=target.workspace).filter(
                Q(client__users=target) | Q(issues__reported_by=target) | Q(client__email=target.email)
            ).distinct()
            data['stats'] = {
                'total_projects':   projects.count(),
                'total_issues':     issues.count(),
                'open_issues':      issues.exclude(status='Done').count(),
                'resolved_issues':  issues.filter(status='Done').count(),
            }
            data['recent_issues'] = list(
                issues.select_related('project', 'reported_by').order_by('-created_at')[:8]
                .values('id', 'title', 'status', 'priority', 'created_at', 'project__name',
                        'reported_by__username', 'reported_by__first_name', 'reported_by__last_name', 'reported_by__role')
            )

        else:
            # Employee roles: developer, tester, devops, designer etc.
            tasks = Task.objects.filter(assignee=target).select_related('project')
            issues = Issue.objects.filter(assignee=target).select_related('project')
            projects = Project.objects.filter(workspace=target.workspace, team_members__user=target).distinct()
            data['stats'] = {
                'total_tasks':      tasks.count() + issues.count(),
                'completed_tasks':  tasks.filter(status='Done').count() + issues.filter(status='Done').count(),
                'in_progress':      tasks.filter(status='In Progress').count() + issues.filter(status='In Progress').count(),
                'total_projects':   projects.count(),
            }
            data['projects'] = list(projects.values('id', 'name', 'slug')[:6])
            data['recent_tasks'] = list(
                tasks.order_by('-created_at')[:8]
                .values('id', 'title', 'status', 'priority', 'created_at', 'project__name',
                        'assignee__username', 'assignee__first_name', 'assignee__last_name', 'assignee__role')
            )
            data['recent_issues'] = list(
                issues.order_by('-created_at')[:8]
                .values('id', 'title', 'status', 'priority', 'created_at', 'project__name',
                        'assignee__username', 'assignee__first_name', 'assignee__last_name', 'assignee__role',
                        'reported_by__username', 'reported_by__first_name', 'reported_by__last_name', 'reported_by__role')
            )

        return Response(data)


class ForgotPasswordView(APIView):
    def post(self, request):
        email = request.data.get('email', '').strip()
        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Security: same response even if email not found
            return Response({'message': 'If this email exists, a reset link has been sent.'})

        # Delete old tokens for this user
        PasswordResetToken.objects.filter(user=user).delete()
        reset_token = PasswordResetToken.objects.create(user=user)

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token.token}"
        name = user.first_name or user.username
        try:
            send_mail(
                'Teople — Password Reset Request',
                f"""Hi {name},

We received a request to reset your Teople account password.

Click the link below to set a new password (valid for 30 minutes):

{reset_url}

If you did not request this, please ignore this email.

— Teople Team""",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            logger.info(
                'Password reset email sent successfully',
                extra={'user_id': user.id, 'email': user.email},
            )
        except Exception:
            logger.exception(
                'Password reset email failed',
                extra={'user_id': user.id, 'email': user.email},
            )
        return Response({'message': 'If this email exists, a reset link has been sent.'})


class ResetPasswordView(APIView):
    def post(self, request):
        token = request.data.get('token', '').strip()
        new_password = request.data.get('new_password', '').strip()

        if not token or not new_password:
            return Response({'error': 'Token and new password are required'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_token = PasswordResetToken.objects.select_related('user').get(token=token)
        except PasswordResetToken.DoesNotExist:
            return Response({'error': 'Invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)

        if reset_token.is_expired():
            reset_token.delete()
            return Response({'error': 'Token has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        user = reset_token.user
        user.set_password(new_password)
        user.save()
        reset_token.delete()
        return Response({'message': 'Password updated successfully.'})
