from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from core.permissions import WorkspaceModuleAccess
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Prefetch, Q
import csv
import hashlib
import logging
from datetime import datetime, time, timedelta
from statistics import fmean

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone

from accounts.models import User
from .models import Client, Project, ProjectMember, Issue, IssueComment, IssueScreenshot, ActivityLog, Feature, Task, TaskComment, TaskCommentAttachment, Module, SubTask
from .serializers import (
    ClientSerializer, ProjectSerializer,
    ProjectWriteSerializer, ProjectMemberSerializer,
    IssueSerializer, IssueWriteSerializer, IssueCommentSerializer, IssueScreenshotSerializer,
    ActivityLogSerializer, FeatureSerializer, FeatureWriteSerializer, annotate_project_counts,
    TaskSerializer, TaskWriteSerializer, TaskCommentSerializer, TaskCommentAttachmentSerializer,
    ModuleSerializer, ModuleWriteSerializer,
    SubTaskSerializer, SubTaskWriteSerializer,
)

logger = logging.getLogger(__name__)


# Custom Pagination Class
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


def log_activity(actor, action, target, project=None, issue=None, extra=None):
    ActivityLog.objects.create(
        actor=actor, action=action, target=target,
        project=project, issue=issue, extra=extra or {}
    )


class IsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == 'admin'


def client_project_filter(user):
    # Prefer explicit reported issue relation; keep client email as a legacy fallback.
    return Q(client__users=user) | Q(issues__reported_by=user) | Q(client__email=user.email)


def projects_for_user(user):
    if not user.workspace_id:
        return Project.objects.none()
    if user.role == 'admin':
        return Project.objects.filter(workspace_id=user.workspace_id)
    if user.role == 'client':
        return Project.objects.filter(
            workspace_id=user.workspace_id,
        ).filter(client_project_filter(user)).distinct()
    return Project.objects.filter(
        workspace_id=user.workspace_id,
        team_members__user=user,
    ).distinct()


def user_can_access_project(user, project):
    if not user.workspace_id or project.workspace_id != user.workspace_id:
        return False
    if user.role == 'admin':
        return True
    if user.role == 'client':
        return Project.objects.filter(pk=project.pk).filter(client_project_filter(user)).exists()
    return project.team_members.filter(user=user).exists()


def user_can_manage_project(user, project):
    if not user.workspace_id or project.workspace_id != user.workspace_id:
        return False
    return user.role == 'admin' or project.team_members.filter(user=user, project_role='manager').exists()


# ─── Client Views ─────────────────────────────────────────────────────────────

class ClientListCreateView(APIView):
    workspace_module = 'clients'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        # Admin and Manager can view all clients
        if request.user.role not in ['admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        clients = Client.objects.filter(workspace=request.user.workspace).annotate(
            _workspace_project_count=Count('projects', distinct=True)
        ).select_related('created_by__workspace').prefetch_related('users__workspace') if request.user.workspace_id else Client.objects.none()
        return Response(ClientSerializer(clients, many=True).data)

    def post(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        workspace = request.user.workspace
        if not workspace:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        serializer = ClientSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        linked_users = serializer.validated_data.get('users', [])
        if any(user.workspace_id != workspace.id for user in linked_users):
            return Response({'error': 'Client login users must belong to this workspace.'}, status=status.HTTP_400_BAD_REQUEST)
        client = serializer.save(created_by=request.user, workspace=workspace)
        log_activity(request.user, 'client_created', client.name, extra={'client_id': client.id})
        return Response(ClientSerializer(client).data, status=status.HTTP_201_CREATED)


class ClientDetailView(APIView):
    permission_classes = [IsAdmin]

    def get_object(self, pk, workspace):
        try:
            return Client.objects.get(pk=pk, workspace=workspace)
        except Client.DoesNotExist:
            return None

    def get(self, request, pk):
        client = self.get_object(pk, request.user.workspace)
        if not client:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ClientSerializer(client).data)

    def patch(self, request, pk):
        client = self.get_object(pk, request.user.workspace)
        if not client:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ClientSerializer(client, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_activity(request.user, 'client_updated', client.name, extra={'client_id': client.id})
        return Response(ClientSerializer(client).data)

    def delete(self, request, pk):
        client = self.get_object(pk, request.user.workspace)
        if not client:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        log_activity(request.user, 'client_deleted', client.name, extra={'client_id': client.id})
        client.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClientProjectsView(APIView):
    """Get all projects for a specific client"""
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        try:
            client = Client.objects.get(pk=pk, workspace=request.user.workspace)
        except Client.DoesNotExist:
            return Response({'error': 'Client not found'}, status=status.HTTP_404_NOT_FOUND)
        
        projects = annotate_project_counts(Project.objects.filter(client=client)).select_related('client').prefetch_related(
            'created_by__workspace',
            'team_members__user__workspace',
            'client__created_by__workspace',
            'client__users__workspace',
            'milestones',
            Prefetch('client__projects', queryset=Project.objects.only('id', 'client_id')),
        )
        return Response(ProjectSerializer(projects, many=True).data)


# ─── Project Views ────────────────────────────────────────────────────────────

class ProjectListCreateView(APIView):
    workspace_module = 'projects'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        projects = projects_for_user(request.user)
        projects = annotate_project_counts(projects).select_related('client', 'created_by__workspace').prefetch_related(
            'client__created_by__workspace',
            'client__users__workspace',
            'team_members__user__workspace',
            'milestones',
            Prefetch('client__projects', queryset=Project.objects.only('id', 'client_id')),
        ).distinct()
        return Response(ProjectSerializer(projects, many=True).data)

    def post(self, request):
        if request.user.role not in ['admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        workspace = request.user.workspace
        if not workspace:
            return Response({'error': 'Workspace is not configured.'}, status=status.HTTP_409_CONFLICT)
        serializer = ProjectWriteSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        client = serializer.validated_data.get('client')
        if not client or client.workspace_id != workspace.id:
            return Response({'error': 'Choose a client from this workspace.'}, status=status.HTTP_400_BAD_REQUEST)
        for entry in serializer.validated_data.get('team', []):
            user_id = entry.get('user_id')
            if user_id and not User.objects.filter(pk=user_id, workspace=workspace).exists():
                return Response({'error': 'Project members must belong to this workspace.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            workspace = type(workspace).objects.select_for_update().get(pk=workspace.pk)
            project_count = workspace.projects.count()
            if project_count >= workspace.project_limit:
                return Response({
                    'error': f'This workspace has reached its {workspace.project_limit}-project {workspace.effective_plan} plan limit.',
                    'usage': {'used': project_count, 'limit': workspace.project_limit},
                }, status=status.HTTP_409_CONFLICT)

            project = serializer.save(created_by=request.user)
            if request.user.role == 'manager':
                ProjectMember.objects.get_or_create(
                    project=project,
                    user=request.user,
                    defaults={'project_role': 'manager'},
                )
            log_activity(request.user, 'project_created', project.name, project=project)
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    workspace_module = 'projects'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, identifier, workspace):
        try:
            projects = annotate_project_counts(Project.objects.filter(workspace=workspace))
            # Try to get by slug first, then by ID
            if str(identifier).isdigit():
                return projects.select_related('client', 'created_by__workspace').prefetch_related(
                    'client__created_by__workspace',
                    'client__users__workspace',
                    'team_members__user__workspace',
                    'milestones',
                    Prefetch('client__projects', queryset=Project.objects.only('id', 'client_id')),
                ).get(pk=identifier)
            else:
                return projects.select_related('client', 'created_by__workspace').prefetch_related(
                    'client__created_by__workspace',
                    'client__users__workspace',
                    'team_members__user__workspace',
                    'milestones',
                    Prefetch('client__projects', queryset=Project.objects.only('id', 'client_id')),
                ).get(slug=identifier)
        except Project.DoesNotExist:
            return None

    def get(self, request, pk=None, slug=None):
        identifier = slug if slug else pk
        project = self.get_object(identifier, request.user.workspace)
        if not project:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        return Response(ProjectSerializer(project).data)

    def patch(self, request, pk=None, slug=None):
        identifier = slug if slug else pk
        project = self.get_object(identifier, request.user.workspace)
        if not project:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_manage_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ProjectWriteSerializer(project, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if request.user.role == 'manager':
            ProjectMember.objects.get_or_create(
                project=project,
                user=request.user,
                defaults={'project_role': 'manager'},
            )
        log_activity(request.user, 'project_updated', project.name, project=project)
        return Response(ProjectSerializer(project).data)

    def delete(self, request, pk=None, slug=None):
        identifier = slug if slug else pk
        project = self.get_object(identifier, request.user.workspace)
        if not project:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_manage_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

class DashboardStatsView(APIView):
    workspace_module = 'projects'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        user = request.user
        if user.role == 'admin':
            # Admin sees all stats
            workspace_projects = Project.objects.filter(workspace_id=user.workspace_id)
            return Response({
                'total_clients':     Client.objects.filter(workspace_id=user.workspace_id).count(),
                'total_projects':    workspace_projects.count(),
                'total_users':       User.objects.filter(workspace_id=user.workspace_id).count(),
                'total_issues':      Issue.objects.filter(project__in=workspace_projects).count(),
                'completed_issues':  Issue.objects.filter(project__in=workspace_projects, status='Done').count(),
                'pending_issues':    Issue.objects.filter(project__in=workspace_projects).exclude(status='Done').count(),
            })
        elif user.role == 'client':
            # Client sees their projects and issues
            client_projects = projects_for_user(user)
            client_issues = Issue.objects.filter(reported_by=user)
            return Response({
                'totalProjects':    client_projects.count(),
                'totalIssues':      client_issues.count(),
                'openIssues':       client_issues.exclude(status='Done').count(),
                'resolvedIssues':   client_issues.filter(status='Done').count(),
            })
        else:
            # Manager: all issues in their projects
            # Tester/Developer/others: only assigned issues
            user_projects = projects_for_user(user)
            if user.role == 'manager':
                user_issues = Issue.objects.filter(project__in=user_projects)
            elif user.role == 'qa_tester':
                from django.db.models import Q
                user_issues = Issue.objects.filter(
                    Q(project__in=user_projects, status='Testing') | Q(assignee=user)
                ).distinct()
            else:
                user_issues = Issue.objects.filter(assignee=user).exclude(status='Testing')
            return Response({
                'total_clients':     0,
                'total_projects':    user_projects.count(),
                'total_users':       0,
                'total_issues':      user_issues.count(),
                'completed_issues':  user_issues.filter(status='Done').count(),
                'pending_issues':    user_issues.exclude(status='Done').count(),
            })


# ─── Issue Views ──────────────────────────────────────────────────────────────

class WorkOverviewView(APIView):
    """Lightweight task list for dashboard project overview charts."""
    workspace_module = 'projects'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        user = request.user
        if user.role == 'admin':
            tasks = Task.objects.filter(project__workspace_id=user.workspace_id)
        elif user.role in ['manager', 'client']:
            tasks = Task.objects.filter(project__in=projects_for_user(user))
        elif user.role == 'qa_tester':
            user_projects = projects_for_user(user)
            tasks = Task.objects.filter(
                Q(project__in=user_projects, status='Testing') | Q(assignee=user)
            ).distinct()
        else:
            tasks = Task.objects.filter(assignee=user).exclude(status='Testing')

        tasks = tasks.select_related('project', 'module', 'feature', 'assignee').order_by('-updated_at', '-created_at')
        data = []
        for task in tasks:
            data.append({
                'id': task.id,
                'task_id': task.task_id,
                'title': task.title,
                'status': task.status,
                'priority': task.priority,
                'project': task.project_id,
                'project_id': task.project_id,
                'project_name': task.project.name,
                'module': task.module_id,
                'module_title': task.module.title if task.module else '',
                'feature': task.feature_id,
                'feature_title': task.feature.title if task.feature else '',
                'assignee': {
                    'id': task.assignee_id,
                    'username': task.assignee.username,
                    'first_name': task.assignee.first_name,
                    'last_name': task.assignee.last_name,
                } if task.assignee else None,
                'created_at': task.created_at,
                'updated_at': task.updated_at,
            })
        return Response(data)


def report_tasks_for_user(user):
    tasks = Task.objects.select_related('project', 'assignee')
    if user.role == 'admin':
        return tasks.filter(project__workspace_id=user.workspace_id)
    if user.role in ('manager', 'client'):
        return tasks.filter(project__in=projects_for_user(user))
    if user.role == 'qa_tester':
        user_projects = projects_for_user(user)
        return tasks.filter(
            Q(project__in=user_projects, status='Testing') | Q(assignee=user)
        ).distinct()
    return tasks.filter(assignee=user)


def scoped_report_tasks(request):
    tasks = report_tasks_for_user(request.user)
    project_id = request.query_params.get('project_id')
    if not project_id:
        return tasks, None
    if not project_id.isdigit():
        return None, Response({'error': 'project_id must be a number.'}, status=status.HTTP_400_BAD_REQUEST)

    project = Project.objects.filter(pk=project_id, workspace_id=request.user.workspace_id).first()
    if not project:
        return None, Response({'error': 'Project not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not user_can_access_project(request.user, project):
        if not tasks.filter(project=project).exists():
            return None, Response({'error': 'Project not found.'}, status=status.HTTP_404_NOT_FOUND)
    return tasks.filter(project=project), project


def safe_csv_value(value):
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return f"'{value}"
    return value


class AnalyticsReportView(APIView):
    workspace_module = 'reports'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        days_value = request.query_params.get('days', '30')
        if not days_value.isdigit() or int(days_value) not in (7, 30, 90):
            return Response({'error': 'days must be 7, 30, or 90.'}, status=status.HTTP_400_BAD_REQUEST)

        tasks, project_or_error = scoped_report_tasks(request)
        if isinstance(project_or_error, Response):
            return project_or_error

        days = int(days_value)
        project_id = project_or_error.pk if project_or_error else 'all'
        cache_key = None
        if request.user.role in ('admin', 'manager', 'client'):
            visible_project_ids = ','.join(str(pk) for pk in projects_for_user(request.user).order_by('pk').values_list('pk', flat=True))
            scope_hash = hashlib.sha256(visible_project_ids.encode()).hexdigest()[:16]
            cache_key = (
                f'tracker-analytics:v1:w{request.user.workspace_id}:'
                f'r{request.user.role}:u{request.user.pk}:s{scope_hash}:p{project_id}:d{days}'
            )
            cached_report = cache.get(cache_key)
            if cached_report is not None:
                return Response(cached_report)

        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)
        start_at = timezone.make_aware(datetime.combine(start_date, time.min))
        open_tasks = tasks.exclude(status='Done')
        completed_in_period = tasks.filter(status='Done', completed_at__gte=start_at)

        created_by_day = dict(
            tasks.filter(created_at__gte=start_at)
            .annotate(report_date=TruncDate('created_at'))
            .values('report_date')
            .annotate(total=Count('pk'))
            .values_list('report_date', 'total')
        )
        completed_by_day = dict(
            completed_in_period.annotate(report_date=TruncDate('completed_at'))
            .values('report_date')
            .annotate(total=Count('pk'))
            .values_list('report_date', 'total')
        )
        trend = [
            {
                'date': (start_date + timedelta(days=offset)).isoformat(),
                'created': created_by_day.get(start_date + timedelta(days=offset), 0),
                'completed': completed_by_day.get(start_date + timedelta(days=offset), 0),
            }
            for offset in range(days)
        ]

        lifecycle_rows = list(completed_in_period.values_list('created_at', 'started_at', 'completed_at'))
        lead_times = [(completed - created).total_seconds() / 86400 for created, _started, completed in lifecycle_rows]
        cycle_times = [
            (completed - started).total_seconds() / 86400
            for _created, started, completed in lifecycle_rows
            if started is not None
        ]
        overdue_tasks = open_tasks.filter(due_date__lt=today)
        workload_rows = open_tasks.values(
            'assignee_id', 'assignee__username', 'assignee__first_name', 'assignee__last_name'
        ).annotate(
            open_tasks=Count('pk'),
            overdue_tasks=Count('pk', filter=Q(due_date__lt=today)),
            estimate_hours=Sum('estimate_hours'),
        ).order_by('-open_tasks', 'assignee__username')

        workload = []
        if request.user.role != 'client':
            for row in workload_rows:
                full_name = f"{row['assignee__first_name']} {row['assignee__last_name']}".strip()
                workload.append({
                    'user_id': row['assignee_id'],
                    'assignee': full_name or row['assignee__username'] or 'Unassigned',
                    'open_tasks': row['open_tasks'],
                    'overdue_tasks': row['overdue_tasks'],
                    'estimate_hours': float(row['estimate_hours'] or 0),
                })

        project_summaries = []
        for row in tasks.values('project_id', 'project__name').annotate(
            total_tasks=Count('pk'),
            completed_tasks=Count('pk', filter=Q(status='Done')),
            blocked_tasks=Count('pk', filter=Q(status='Blocked')),
            overdue_tasks=Count(
                'pk',
                filter=Q(due_date__lt=today) & ~Q(status='Done'),
            ),
        ).order_by('project__name'):
            project_summaries.append({
                'project_id': row['project_id'],
                'project_name': row['project__name'],
                'total_tasks': row['total_tasks'],
                'completed_tasks': row['completed_tasks'],
                'blocked_tasks': row['blocked_tasks'],
                'overdue_tasks': row['overdue_tasks'],
                'completion_rate': round(row['completed_tasks'] * 100 / row['total_tasks']) if row['total_tasks'] else 0,
            })

        status_breakdown = dict(tasks.values_list('status').annotate(total=Count('pk')))
        completed_count = completed_in_period.count()
        report = {
            'period_days': days,
            'summary': {
                'total_tasks': tasks.count(),
                'completed_tasks': completed_count,
                'open_tasks': open_tasks.count(),
                'blocked_tasks': tasks.filter(status='Blocked').count(),
                'overdue_tasks': overdue_tasks.count(),
                'throughput_per_week': round(completed_count * 7 / days, 2),
                'lead_time_avg_days': round(fmean(lead_times), 2) if lead_times else None,
                'cycle_time_avg_days': round(fmean(cycle_times), 2) if cycle_times else None,
            },
            'status_breakdown': status_breakdown,
            'trend': trend,
            'workload': workload,
            'projects': project_summaries,
        }
        if cache_key:
            cache.set(cache_key, report, timeout=30)
        return Response(report)


class AnalyticsExportView(APIView):
    workspace_module = 'reports'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        tasks, error = scoped_report_tasks(request)
        if error:
            return error

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="tracker-report.csv"'
        writer = csv.writer(response)
        if request.user.role == 'client':
            writer.writerow([
                'Project Key', 'Project', 'Total Tasks', 'Completed Tasks',
                'Blocked Tasks', 'Overdue Tasks', 'Completion Rate',
            ])
            project_rows = tasks.values('project__project_key', 'project__name').annotate(
                total_tasks=Count('pk'),
                completed_tasks=Count('pk', filter=Q(status='Done')),
                blocked_tasks=Count('pk', filter=Q(status='Blocked')),
                overdue_tasks=Count(
                    'pk',
                    filter=Q(due_date__lt=timezone.localdate()) & ~Q(status='Done'),
                ),
            ).order_by('project__name')
            for row in project_rows:
                completion_rate = round(row['completed_tasks'] * 100 / row['total_tasks']) if row['total_tasks'] else 0
                writer.writerow([
                    safe_csv_value(row['project__project_key']),
                    safe_csv_value(row['project__name']),
                    row['total_tasks'],
                    row['completed_tasks'],
                    row['blocked_tasks'],
                    row['overdue_tasks'],
                    completion_rate,
                ])
            return response

        writer.writerow([
            'Project Key', 'Project', 'Task ID', 'Title', 'Status', 'Priority',
            'Assignee', 'Due Date', 'Estimate Hours', 'Created At', 'Started At', 'Completed At',
        ])
        for task in tasks.select_related('project', 'assignee').order_by('project__name', 'task_id'):
            assignee = task.assignee.get_full_name() or task.assignee.username if task.assignee else ''
            values = [
                task.project.project_key,
                task.project.name,
                task.task_id,
                task.title,
                task.status,
                task.priority,
                assignee,
                task.due_date,
                task.estimate_hours,
                task.created_at,
                task.started_at,
                task.completed_at,
            ]
            writer.writerow([safe_csv_value(value) for value in values])
        return response


class IssueListCreateView(APIView):
    workspace_module = 'issues'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        user = request.user

        if user.role == 'admin':
            # Admin sees all issues
            issues = Issue.objects.filter(project__workspace_id=user.workspace_id)
        elif user.role == 'client':
            # Client sees only issues they reported
            issues = Issue.objects.filter(reported_by=user)
        elif user.role == 'qa_tester':
            # Tester sees: Testing status issues in their projects OR directly assigned to them
            from django.db.models import Q
            user_projects = Project.objects.filter(team_members__user=user)
            issues = Issue.objects.filter(
                Q(project__in=user_projects, status='Testing') | Q(assignee=user)
            ).distinct()
        elif user.role == 'manager':
            # Manager sees all issues in their projects
            user_projects = Project.objects.filter(team_members__user=user)
            issues = Issue.objects.filter(project__in=user_projects)
        else:
            # Developer / other employees: ONLY issues assigned to them (excludes Testing — those go to tester)
            issues = Issue.objects.filter(assignee=user).exclude(status='Testing')

        # Filter by query parameters
        status_filter = request.query_params.get('status')
        assignee_filter = request.query_params.get('assignee')

        if status_filter:
            issues = issues.filter(status=status_filter)

        if assignee_filter:
            if assignee_filter == 'me':
                issues = issues.filter(assignee=user)
            else:
                issues = issues.filter(assignee_id=assignee_filter)

        issues = issues.select_related('project', 'reported_by', 'assignee').prefetch_related(
            'comments__author',
            'comments__comment_screenshots',
            'screenshots',
        ).order_by('-updated_at', '-created_at')
        
        # Apply pagination
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(issues, request)
        if page is not None:
            serializer = IssueSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        # Fallback if pagination fails
        return Response(IssueSerializer(issues, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = IssueWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.validated_data['project']
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        issue = serializer.save(reported_by=request.user)

        # Save multiple screenshots
        for img in request.FILES.getlist('screenshots'):
            IssueScreenshot.objects.create(issue=issue, image=img)

        log_activity(request.user, 'issue_created', issue.title, project=issue.project, issue=issue)
        self._send_notifications(issue)
        self._send_websocket_notification(issue, request.user)
        
        return Response(IssueSerializer(issue, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def _send_notifications(self, issue):
        """Notify only Admin, Managers, and Testers when new issue is created"""
        project = issue.project
        recipients = set()

        # 1. All admins
        admins = User.objects.filter(role='admin', workspace=project.workspace)
        recipients.update(admins.values_list('email', flat=True))

        # 2. Managers of this project ONLY
        managers = project.team_members.filter(project_role='manager').select_related('user')
        recipients.update([m.user.email for m in managers if m.user.email])

        # NOTE: Testers and Employees will be notified ONLY when issue is assigned to them

        recipients = [email for email in recipients if email]

        if recipients:
            subject = f'New Issue Reported: {issue.title}'
            message = f"""A new issue has been reported by {issue.reported_by.username}:

Project  : {project.name}
Title    : {issue.title}
Type     : {issue.get_issue_type_display()}
Priority : {issue.get_priority_display()}

Description:
{issue.description}

Manager: Please review and assign this issue to a team member.
View details: {settings.FRONTEND_URL}/issues/{issue.id}
"""
            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
                logger.info('Issue notification email sent', extra={'issue_id': issue.id, 'recipients': len(recipients)})
            except Exception:
                logger.exception('Issue notification email failed', extra={'issue_id': issue.id, 'recipients': recipients})
    
    def _send_websocket_notification(self, issue, reporter):
        """Send real-time WebSocket notification to managers and admins"""
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        
        project = issue.project
        recipient_ids = set()
        
        # 1. All admins
        admins = User.objects.filter(role='admin', workspace=project.workspace)
        recipient_ids.update(admins.values_list('id', flat=True))
        
        # 2. Managers of this project ONLY
        managers = project.team_members.filter(project_role='manager').select_related('user')
        recipient_ids.update([m.user.id for m in managers])
        
        # NOTE: Testers and Employees will be notified ONLY when issue is assigned to them
        
        # Remove reporter from recipients
        recipient_ids.discard(reporter.id)
        
        print(f"\n=== NEW ISSUE WEBSOCKET NOTIFICATION ===")
        print(f"Issue: {issue.title} (ID: {issue.id})")
        print(f"Project: {project.name}")
        print(f"Reporter: {reporter.username}")
        print(f"Recipients: {list(recipient_ids)}")
        
        issue_data = IssueSerializer(issue, context={'request': None}).data
        
        for recipient_id in recipient_ids:
            group_name = f'notifications_{recipient_id}'
            try:
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'data_update',
                        'entity': 'issue',
                        'action': 'created',
                        'data': {
                            'issue': issue_data,
                            'message': f'New issue reported: {issue.title}',
                            'reporter': reporter.username
                        }
                    }
                )
                print(f"✅ Sent to {group_name}")
            except Exception as e:
                print(f"❌ Error sending to {group_name}: {e}")
        
        print(f"=== END NOTIFICATION ===\n")


class IssueDetailView(APIView):
    workspace_module = 'issues'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, pk, user):
        try:
            issue = Issue.objects.select_related('project', 'reported_by', 'assignee').prefetch_related(
                'comments__author',
                'comments__comment_screenshots',
                'screenshots',
            ).get(pk=pk)
            # Check permissions
            if user.role == 'admin':
                return issue
            elif user.role == 'client' and issue.reported_by == user:
                return issue
            elif issue.project.team_members.filter(user=user).exists():
                return issue
            # Permission denied but issue exists
            return None
        except Issue.DoesNotExist:
            return None

    def get(self, request, pk):
        issue = self.get_object(pk, request.user)
        if not issue:
            # Debug: Check if issue exists but user lacks permission
            try:
                existing_issue = Issue.objects.get(pk=pk)
                print(f"🔒 Issue {pk} exists but user {request.user.username} lacks permission")
                print(f"   Issue project: {existing_issue.project.name}, User role: {request.user.role}")
                print(f"   Is team member: {existing_issue.project.team_members.filter(user=request.user).exists()}")
            except Issue.DoesNotExist:
                print(f"❌ Issue {pk} does not exist in database")
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(IssueSerializer(issue, context={'request': request}).data)

    def patch(self, request, pk):
        issue = self.get_object(pk, request.user)
        if not issue:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        is_admin = user.role == 'admin'
        is_manager = issue.project.team_members.filter(user=user, project_role='manager').exists()
        is_team_member = issue.project.team_members.filter(user=user).exists()
        is_reporter = issue.reported_by == user
        
        # Check if only status is being updated
        updating_only_status = 'status' in request.data and len(request.data) == 1
        
        print(f"\n=== ISSUE UPDATE DEBUG ===")
        print(f"Issue ID: {pk}")
        print(f"User: {user.username} (Role: {user.role})")
        print(f"Request Data: {request.data}")
        print(f"Old Status: {issue.status}")
        print(f"Is Reporter: {is_reporter}")
        print(f"Is Admin: {is_admin}")
        print(f"Is Manager: {is_manager}")
        print(f"Is Team Member: {is_team_member}")
        
        is_tester = user.role == 'qa_tester' and is_team_member
        # Tester can update status + assignee only
        updating_status_or_assignee = all(k in ('status', 'assignee') for k in request.data.keys())
        requested_status = request.data.get('status')

        if requested_status == 'Done' and not (is_admin or is_manager or is_tester):
            return Response(
                {'error': 'Only a tester, manager, or admin can mark an issue as Done.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Permission logic:
        # 1. Admin can update everything
        # 2. Manager can update everything
        # 3. Reporter (client) can update everything except status/assignee (those are for team management)
        # 4. Team members can update status only
        # 5. Tester can update status and assignee
        
        if is_admin or is_manager:
            pass  # Full access
        elif is_reporter:
            # Reporter can update all fields except status/assignee (those are for team management)
            restricted_fields = {'status', 'assignee'}
            if any(k in restricted_fields for k in request.data.keys()):
                return Response({'error': 'You cannot update status or assignee. These are managed by the development team.'}, status=status.HTTP_403_FORBIDDEN)
        elif is_tester and updating_status_or_assignee:
            pass  # Tester can update status and assignee
        elif updating_only_status and is_team_member:
            pass  # Any team member can update status
        else:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = IssueWriteSerializer(issue, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        old_status   = issue.status
        old_assignee = issue.assignee_id
        serializer.save()
        issue.refresh_from_db()

        # ── Handle ASSIGNEE change ────────────────────────────────────────────
        if 'assignee' in request.data and issue.assignee_id != old_assignee:
            if old_status == 'Testing':
                # Tester reassigning → status To Do, save as developer, notify
                issue.status = 'To Do'
                issue.developer = issue.assignee
                issue.save(update_fields=['status', 'developer'])
                log_activity(request.user, 'assignee_changed', issue.title, project=issue.project, issue=issue,
                             extra={'assignee': issue.assignee.username if issue.assignee else None, 'reason': 'tester_reassigned'})
                if issue.assignee:
                    self._notify_developer(issue, issue.assignee, request.user)
                if issue.reported_by:
                    self._notify_client(issue, old_status, 'To Do', request.user)
            else:
                # Normal assignee change → save as developer
                if issue.assignee_id:
                    issue.developer = issue.assignee
                    issue.save(update_fields=['developer'])
                log_activity(request.user, 'assignee_changed', issue.title, project=issue.project, issue=issue,
                             extra={'assignee': issue.assignee.username if issue.assignee else None})

        # ── Handle STATUS change ──────────────────────────────────────────────
        elif 'status' in request.data and issue.status != old_status:
            if issue.status == 'Testing' and old_status != 'Testing':
                # Auto-assign tester
                tester_member = issue.project.team_members.filter(project_role='tester').select_related('user').first()
                if tester_member:
                    issue.assignee = tester_member.user
                    issue.save(update_fields=['assignee'])
                    log_activity(request.user, 'assignee_changed', issue.title, project=issue.project, issue=issue,
                                 extra={'assignee': tester_member.user.username, 'reason': 'auto_testing'})
                    self._notify_tester(issue, tester_member.user, request.user)
            elif old_status == 'Testing' and issue.status not in ('Testing', 'Done'):
                # Tester rejected → restore developer, status To Do
                if issue.developer_id:
                    issue.assignee = issue.developer
                    issue.status = 'To Do'
                    issue.save(update_fields=['assignee', 'status'])
                    log_activity(request.user, 'assignee_changed', issue.title, project=issue.project, issue=issue,
                                 extra={'assignee': issue.developer.username, 'reason': 'rejected_from_testing'})
                    self._notify_developer(issue, issue.developer, request.user)
                if issue.reported_by:
                    self._notify_client(issue, old_status, 'To Do', request.user)
            elif issue.status == 'Done' and issue.developer_id:
                # Tester approved → notify developer
                self._notify_developer_approved(issue, issue.developer, request.user)

            log_activity(request.user, 'status_changed', issue.title, project=issue.project, issue=issue,
                         extra={'from': old_status, 'to': issue.status})
            if issue.reported_by:
                self._notify_client(issue, old_status, issue.status, request.user)

        else:
            log_activity(request.user, 'issue_updated', issue.title, project=issue.project, issue=issue)

        print(f"New Status: {issue.status}")
        print(f"=== END DEBUG ===\n")

        return Response(IssueSerializer(issue, context={'request': request}).data)

    def _notify_tester(self, issue, tester, changed_by):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        issue_data = IssueSerializer(issue, context={'request': None}).data
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{tester.id}',
                {
                    'type': 'data_update',
                    'entity': 'issue',
                    'action': 'assigned_for_testing',
                    'data': {
                        'issue': issue_data,
                        'message': f'Issue "{issue.title}" is ready for testing and assigned to you',
                        'changed_by': changed_by.username,
                    }
                }
            )
        except Exception as e:
            print(f"❌ Tester notify error: {e}")

    def _notify_developer(self, issue, developer, changed_by):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        issue_data = IssueSerializer(issue, context={'request': None}).data
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{developer.id}',
                {
                    'type': 'data_update',
                    'entity': 'issue',
                    'action': 'rejected_from_testing',
                    'data': {
                        'issue': issue_data,
                        'message': f'Issue "{issue.title}" was rejected by tester and needs your attention',
                        'changed_by': changed_by.username,
                    }
                }
            )
        except Exception as e:
            print(f"❌ Developer notify error: {e}")

    def _notify_developer_approved(self, issue, developer, changed_by):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        issue_data = IssueSerializer(issue, context={'request': None}).data
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{developer.id}',
                {
                    'type': 'data_update',
                    'entity': 'issue',
                    'action': 'approved_from_testing',
                    'data': {
                        'issue': issue_data,
                        'message': f'Issue "{issue.title}" was approved by tester and marked Done',
                        'changed_by': changed_by.username,
                    }
                }
            )
        except Exception as e:
            print(f"Developer approval notify error: {e}")

    def _notify_client(self, issue, old_status, new_status, changed_by):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        client = issue.reported_by
        if not client:
            return
        status_messages = {
            'In Progress': f'Your issue "{issue.title}" is now being worked on.',
            'Testing':     f'Your issue "{issue.title}" is under testing.',
            'Done':        f'Your issue "{issue.title}" has been resolved! ✅',
            'To Do':       f'Your issue "{issue.title}" has been moved back to To Do.',
        }
        message = status_messages.get(new_status, f'Your issue "{issue.title}" status changed to {new_status}.')
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{client.id}',
                {
                    'type': 'data_update',
                    'entity': 'issue',
                    'action': 'status_changed_client',
                    'data': {
                        'issue_id': issue.id,
                        'issue_title': issue.title,
                        'old_status': old_status,
                        'new_status': new_status,
                        'message': message,
                        'changed_by': changed_by.username,
                    }
                }
            )
        except Exception as e:
            print(f"❌ Client notify error: {e}")

    def delete(self, request, pk):
        issue = self.get_object(pk, request.user)
        if not issue:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        is_admin = user.role == 'admin'
        is_manager = issue.project.team_members.filter(user=user, project_role='manager').exists()
        is_reporter = issue.reported_by == user
        
        # Admin, manager, or reporter can delete
        if not (is_admin or is_manager or is_reporter):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        issue.delete()
        log_activity(request.user, 'issue_deleted', issue.title)
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssueCommentView(APIView):
    workspace_module = 'issues'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, issue_id):
        try:
            issue = Issue.objects.get(pk=issue_id)
        except Issue.DoesNotExist:
            return Response({'error': 'Issue not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user has access to this issue
        user = request.user
        if user.role not in ['admin'] and issue.reported_by != user and not issue.project.team_members.filter(user=user).exists():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        text = (request.data.get('text', '') or '').strip() if hasattr(request.data, 'get') else str(request.data).strip()
        parent_id = request.data.get('parent_id') if hasattr(request.data, 'get') else None
        uploaded_files = request.FILES.getlist('screenshots')

        if not text and not uploaded_files:
            return Response({'error': 'Comment text or screenshot is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Handle parent comment for replies
        parent_comment = None
        if parent_id:
            try:
                parent_comment = IssueComment.objects.get(pk=parent_id, issue=issue)
            except IssueComment.DoesNotExist:
                return Response({'error': 'Parent comment not found'}, status=status.HTTP_400_BAD_REQUEST)
        
        comment = IssueComment.objects.create(
            issue=issue, 
            author=user, 
            text=text or 'Attached screenshot(s)',
            parent=parent_comment
        )
        uploaded_screenshots = [
            IssueScreenshot.objects.create(issue=issue, comment=comment, image=img)
            for img in uploaded_files
        ]
        log_activity(user, 'comment_added', issue.title, project=issue.project, issue=issue)
        
        # Send real-time update via WebSocket
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        if channel_layer:
            print(f"\n=== WEBSOCKET DEBUG ===")
            print(f"Issue ID: {issue.id}")
            print(f"Comment Author: {user.username}")
            print(f"Comment Text: {text}")
            
            # Get all users who should receive this update
            project_members = issue.project.team_members.all()
            recipient_ids = [issue.reported_by.id] if issue.reported_by else []
            recipient_ids.extend([pm.user.id for pm in project_members])
            
            # Remove duplicates and current user
            recipient_ids = list(set(recipient_ids))
            if user.id in recipient_ids:
                recipient_ids.remove(user.id)
            
            print(f"Recipients: {recipient_ids}")
            
            # Send to each recipient
            comment_data = IssueCommentSerializer(comment, context={'request': request}).data
            comment_data['uploaded_screenshots'] = IssueScreenshotSerializer(uploaded_screenshots, many=True, context={'request': request}).data
            print(f"Comment Data: {comment_data}")
            
            for recipient_id in recipient_ids:
                group_name = f'notifications_{recipient_id}'
                print(f"Sending to group: {group_name}")
                
                try:
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            'type': 'data_update',
                            'entity': 'comment',
                            'action': 'created',
                            'data': {
                                'issue_id': issue.id,
                                'comment': comment_data,
                                'author': user.username
                            }
                        }
                    )
                    print(f"✅ Sent to {group_name}")
                except Exception as e:
                    print(f"❌ Error sending to {group_name}: {e}")
            
            print(f"=== END WEBSOCKET DEBUG ===\n")
        else:
            print("❌ Channel layer not available")
        
        response_data = IssueCommentSerializer(comment, context={'request': request}).data
        response_data['uploaded_screenshots'] = IssueScreenshotSerializer(uploaded_screenshots, many=True, context={'request': request}).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class CommentLikeView(APIView):
    """Toggle like on a comment (supports IssueComment, TaskComment, SubTaskComment)"""
    workspace_module = 'issues'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def post(self, request, comment_id):
        user = request.user
        comment = None
        comment_type = None
        project = None
        recipient_ids = []
        
        # Try to find comment in IssueComment first
        try:
            comment = IssueComment.objects.get(pk=comment_id)
            comment_type = 'issue'
            issue = comment.issue
            project = issue.project
            
            # Check permission for issue comment
            if user.role not in ['admin'] and issue.reported_by != user and not project.team_members.filter(user=user).exists():
                return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
            
            # Get recipients for issue
            project_members = issue.project.team_members.all()
            recipient_ids = [issue.reported_by.id] if issue.reported_by else []
            recipient_ids.extend([pm.user.id for pm in project_members])
        except IssueComment.DoesNotExist:
            pass
        
        # If not found, try TaskComment
        if comment is None:
            try:
                comment = TaskComment.objects.get(pk=comment_id)
                comment_type = 'task'
                task = comment.task
                project = task.project
                
                # Check permission for task comment
                if user.role not in ['admin'] and task.assignee != user and task.reporter != user and not project.team_members.filter(user=user).exists():
                    return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
                
                # Get recipients for task
                project_members = project.team_members.all()
                recipient_ids = []
                if task.assignee:
                    recipient_ids.append(task.assignee.id)
                if task.reporter:
                    recipient_ids.append(task.reporter.id)
                recipient_ids.extend([pm.user.id for pm in project_members])
            except TaskComment.DoesNotExist:
                pass
        
        # If not found, try SubTaskComment
        if comment is None:
            try:
                comment = SubTaskComment.objects.get(pk=comment_id)
                comment_type = 'subtask'
                subtask = comment.subtask
                task = subtask.task
                project = task.project
                
                # Check permission for subtask comment
                if user.role not in ['admin'] and subtask.assignee != user and task.assignee != user and task.reporter != user and not project.team_members.filter(user=user).exists():
                    return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
                
                # Get recipients for subtask
                project_members = project.team_members.all()
                recipient_ids = []
                if subtask.assignee:
                    recipient_ids.append(subtask.assignee.id)
                if task.assignee:
                    recipient_ids.append(task.assignee.id)
                if task.reporter:
                    recipient_ids.append(task.reporter.id)
                recipient_ids.extend([pm.user.id for pm in project_members])
            except SubTaskComment.DoesNotExist:
                return Response({'error': 'Comment not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Toggle like
        if comment.likes.filter(id=user.id).exists():
            comment.likes.remove(user)
            liked = False
        else:
            comment.likes.add(user)
            liked = True
        
        # Send real-time update via WebSocket
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        if channel_layer and project:
            # Remove duplicates but keep current user to update their UI
            recipient_ids = list(set(recipient_ids))
            
            for recipient_id in recipient_ids:
                group_name = f'notifications_{recipient_id}'
                
                try:
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            'type': 'data_update',
                            'entity': 'comment_like',
                            'action': 'toggled',
                            'data': {
                                'issue_id': comment.issue.id if comment_type == 'issue' else None,
                                'comment_id': comment.id,
                                'likes_count': comment.likes_count,
                                'user_id': user.id,
                                'liked': liked,
                                'comment_type': comment_type
                            }
                        }
                    )
                except Exception as e:
                    print(f"❌ Error sending like update: {e}")
        
        return Response({
            'liked': liked,
            'likes_count': comment.likes_count
        })


class ActivityLogListView(APIView):
    workspace_module = 'activity'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        user = request.user
        if user.role == 'admin':
            logs = ActivityLog.objects.filter(
                Q(project__workspace_id=user.workspace_id) | Q(actor__workspace_id=user.workspace_id)
            ).select_related('actor', 'project', 'issue')
        elif user.role == 'manager':
            # Manager sees activity for their projects
            user_projects = projects_for_user(user)
            logs = ActivityLog.objects.filter(project__in=user_projects).select_related('actor', 'project', 'issue')
        else:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        action = request.query_params.get('action')
        project_id = request.query_params.get('project')
        actor_id = request.query_params.get('actor')
        search = request.query_params.get('search')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        limit = request.query_params.get('limit')

        if action:
            logs = logs.filter(action=action)
        if project_id and str(project_id).isdigit():
            logs = logs.filter(project_id=project_id)
        if actor_id and str(actor_id).isdigit():
            logs = logs.filter(actor_id=actor_id)
        if search:
            logs = logs.filter(Q(target__icontains=search) | Q(actor__username__icontains=search) | Q(actor__first_name__icontains=search) | Q(actor__last_name__icontains=search))
        if date_from:
            logs = logs.filter(created_at__date__gte=date_from)
        if date_to:
            logs = logs.filter(created_at__date__lte=date_to)

        max_limit = 100 if user.role == 'admin' else 50
        if limit and str(limit).isdigit():
            max_limit = min(int(limit), 200)
        logs = logs[:max_limit]
        return Response(ActivityLogSerializer(logs, many=True).data)


# ─── Feature (Epic) Views ─────────────────────────────────────────────────────

class FeatureListCreateView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def _can_access(self, user, project):
        return user_can_access_project(user, project)

    def get(self, request, project_id):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)
        if not self._can_access(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        features = Feature.objects.filter(project=project).prefetch_related('tasks', 'assignee', 'reporter')
        return Response(FeatureSerializer(features, many=True).data)

    def post(self, request, project_id):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Only admin or project manager can create features'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        data['project'] = project_id
        serializer = FeatureWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        feature = serializer.save(reporter=request.user)
        log_activity(request.user, 'feature_created', feature.title, project=project,
                     extra={'feature_id': feature.feature_id})
        return Response(FeatureSerializer(feature).data, status=status.HTTP_201_CREATED)


class FeatureDetailView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, project_identifier, feature_id):
        try:
            # Handle both project ID and project slug
            if str(project_identifier).isdigit():
                return Feature.objects.prefetch_related('tasks__assignee', 'tasks__reporter').get(
                    project_id=project_identifier, feature_id=feature_id
                )
            else:
                project = Project.objects.get(slug=project_identifier)
                return Feature.objects.prefetch_related('tasks__assignee', 'tasks__reporter').get(
                    project=project, feature_id=feature_id
                )
        except (Feature.DoesNotExist, Project.DoesNotExist):
            return None

    def get(self, request, project_id=None, project_slug=None, feature_id=None):
        project_identifier = project_slug if project_slug else project_id
        feature = self.get_object(project_identifier, feature_id)
        if not feature:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, feature.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return Response(FeatureSerializer(feature).data)

    def patch(self, request, project_id=None, project_slug=None, feature_id=None):
        project_identifier = project_slug if project_slug else project_id
        feature = self.get_object(project_identifier, feature_id)
        if not feature:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = feature.project.team_members.filter(user=user, project_role='manager').exists()
        is_member  = feature.project.team_members.filter(user=user).exists()
        updating_only_status = list(request.data.keys()) == ['status']
        if not (user.role == 'admin' or is_manager or (is_member and updating_only_status)):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        serializer = FeatureWriteSerializer(feature, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_activity(request.user, 'feature_updated', feature.title, project=feature.project,
                     extra={'feature_id': feature.feature_id})
        return Response(FeatureSerializer(feature).data)

    def delete(self, request, project_id=None, project_slug=None, feature_id=None):
        project_identifier = project_slug if project_slug else project_id
        feature = self.get_object(project_identifier, feature_id)
        if not feature:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = feature.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        title = feature.title
        project = feature.project
        feature_key = feature.feature_id
        feature.delete()
        log_activity(request.user, 'feature_deleted', title, project=project,
                     extra={'feature_id': feature_key})
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Task Views ───────────────────────────────────────────────────────────────

class TaskListCreateView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, project_id=None, project_slug=None, feature_id=None):
        try:
            if project_slug:
                project = Project.objects.get(slug=project_slug)
                feature = Feature.objects.get(project=project, feature_id=feature_id)
            else:
                feature = Feature.objects.get(project_id=project_id, feature_id=feature_id)
        except (Feature.DoesNotExist, Project.DoesNotExist):
            return Response({'error': 'Feature not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, feature.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        tasks = feature.tasks.select_related('assignee', 'reporter')
        return Response(TaskSerializer(tasks, many=True).data)

    def post(self, request, project_id=None, project_slug=None, feature_id=None):
        try:
            if project_slug:
                project = Project.objects.get(slug=project_slug)
                feature = Feature.objects.get(project=project, feature_id=feature_id)
                project_id = project.id
            else:
                feature = Feature.objects.get(project_id=project_id, feature_id=feature_id)
        except (Feature.DoesNotExist, Project.DoesNotExist):
            return Response({'error': 'Feature not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, feature.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        user = request.user
        is_manager = feature.project.team_members.filter(user=user, project_role='manager').exists()
        is_member  = feature.project.team_members.filter(user=user).exists()
        if user.role != 'admin' and not is_manager and not is_member:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        data['feature'] = feature.id
        data['module'] = feature.module_id if feature.module else None
        data['project'] = project_id
        if not data.get('assignee') and feature.assignee_id:
            data['assignee'] = feature.assignee_id
        
        print(f"\n=== TASK CREATE DEBUG ===")
        print(f"Feature DB ID: {feature.id}")
        print(f"Feature String ID: {feature.feature_id}")
        print(f"Module ID: {feature.module_id if feature.module else None}")
        print(f"Project ID: {project_id}")
        print(f"Data being sent to serializer: {data}")
        
        serializer = TaskWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(reporter=request.user)
        log_activity(request.user, 'task_created', task.title, project=task.project,
                     extra={'task_id': task.task_id, 'feature_id': feature.feature_id})
        if task.assignee_id and not feature.assignee_id:
            feature.assignee = task.assignee
            feature.save(update_fields=['assignee'])
        
        print(f"Task saved: ID={task.id}, feature_id={task.feature_id}, module_id={task.module_id}")
        print(f"=== END DEBUG ===\n")
        
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


class TaskDetailView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, project_identifier, task_identifier):
        try:
            # Handle both project ID and project slug
            if str(project_identifier).isdigit():
                project_id = project_identifier
            else:
                project = Project.objects.get(slug=project_identifier)
                project_id = project.id
            
            # Try both task_id (string) and id (integer)
            if str(task_identifier).isdigit():
                return Task.objects.select_related('assignee', 'reporter', 'feature', 'project').get(
                    project_id=project_id, id=int(task_identifier)
                )
            else:
                return Task.objects.select_related('assignee', 'reporter', 'feature', 'project').get(
                    project_id=project_id, task_id=task_identifier
                )
        except (Task.DoesNotExist, Project.DoesNotExist):
            return None

    def get(self, request, project_id=None, project_slug=None, task_id=None):
        project_identifier = project_slug if project_slug else project_id
        task = self.get_object(project_identifier, task_id)
        if not task:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, task.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TaskSerializer(task).data)

    def patch(self, request, project_id=None, project_slug=None, task_id=None):
        project_identifier = project_slug if project_slug else project_id
        task = self.get_object(project_identifier, task_id)
        if not task:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_admin = user.role == 'admin'
        is_manager = task.project.team_members.filter(user=user, project_role='manager').exists()
        is_member  = task.project.team_members.filter(user=user).exists()
        is_assignee = task.assignee == user
        is_tester = user.role == 'qa_tester' and is_member
        updating_only_status = list(request.data.keys()) == ['status']
        updating_status_or_assignee = all(k in ('status', 'assignee') for k in request.data.keys())
        requested_status = request.data.get('status')

        if requested_status == 'Done' and not (is_admin or is_manager or is_tester):
            return Response({'error': 'Only a tester, manager, or admin can mark a task as Done.'}, status=status.HTTP_403_FORBIDDEN)

        if not (is_admin or is_manager or (is_tester and updating_status_or_assignee) or (is_assignee and updating_only_status)):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = TaskWriteSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_status = task.status
        serializer.save()
        task.refresh_from_db()
        if set(request.data.keys()) - {'status'}:
            log_activity(request.user, 'task_updated', task.title, project=task.project,
                         extra={'task_id': task.task_id})

        if 'assignee' in request.data and 'status' not in request.data:
            # Tester manually reassigning from Testing → treat as rejection, restore To Do
            if old_status == 'Testing' and is_tester:
                task.status = 'To Do'
                task.save(update_fields=['status'])
                self._notify_user(task, task.assignee, request.user,
                                  f'Task "{task.title}" was reassigned to you', 'task_reassigned')

        elif 'status' in request.data and task.status != old_status:
            if task.status == 'Testing' and old_status != 'Testing':
                # Save current assignee as developer, auto-assign tester
                if task.assignee_id:
                    task.developer = task.assignee
                    task.save(update_fields=['developer'])
                tester_member = task.project.team_members.filter(project_role='tester').select_related('user').first()
                if tester_member:
                    task.assignee = tester_member.user
                    task.save(update_fields=['assignee'])
                    self._notify_user(task, tester_member.user, request.user,
                                      f'Task "{task.title}" is ready for testing and assigned to you', 'task_testing')
            elif old_status == 'Testing' and task.status not in ('Testing', 'Done'):
                # Tester rejected → restore developer
                if task.developer_id:
                    task.assignee = task.developer
                    task.status = 'To Do'
                    task.save(update_fields=['assignee', 'status'])
                    self._notify_user(task, task.developer, request.user,
                                      f'Task "{task.title}" was rejected by tester and needs your attention', 'task_rejected')
            elif task.status == 'Done' and task.developer_id:
                self._notify_user(task, task.developer, request.user,
                                  f'Task "{task.title}" was approved by tester and marked Done', 'task_approved')

            log_activity(request.user, 'status_changed', task.title, project=task.project,
                         extra={'from': old_status, 'to': task.status})
        return Response(TaskSerializer(task).data)

    def _notify_user(self, task, recipient, changed_by, message, action):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if not channel_layer or not recipient:
            return
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{recipient.id}',
                {
                    'type': 'data_update',
                    'entity': 'task',
                    'action': action,
                    'data': {
                        'task_id': task.id,
                        'task_key': task.task_id,
                        'task_title': task.title,
                        'project_id': task.project_id,
                        'task': TaskSerializer(task).data,
                        'message': message,
                        'changed_by': changed_by.username,
                    }
                }
            )
        except Exception as e:
            print(f'Task notify error: {e}')

    def delete(self, request, project_id=None, project_slug=None, task_id=None):
        project_identifier = project_slug if project_slug else project_id
        task = self.get_object(project_identifier, task_id)
        if not task:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = task.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        title = task.title
        project = task.project
        task_key = task.task_id
        task.delete()
        log_activity(request.user, 'task_deleted', title, project=project,
                     extra={'task_id': task_key})
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskCommentView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, project_id=None, project_slug=None, task_id=None):
        try:
            if project_slug:
                project = Project.objects.get(slug=project_slug)
                task = Task.objects.get(project=project, task_id=task_id)
            else:
                task = Task.objects.get(project_id=project_id, task_id=task_id)
        except (Task.DoesNotExist, Project.DoesNotExist):
            return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user has access to this task
        user = request.user
        if user.role not in ['admin'] and task.assignee != user and not task.project.team_members.filter(user=user).exists():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        text = (request.data.get('text', '') or '').strip()
        uploaded_files = request.FILES.getlist('screenshots')
        if not text and not uploaded_files:
            return Response({'error': 'Comment text or screenshot is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        comment = TaskComment.objects.create(
            task=task,
            author=user,
            text=text or 'Attached screenshot(s)'
        )
        uploaded_attachments = [
            TaskCommentAttachment.objects.create(comment=comment, image=img)
            for img in uploaded_files
        ]
        response_data = TaskCommentSerializer(comment, context={'request': request}).data
        response_data['uploaded_screenshots'] = TaskCommentAttachmentSerializer(uploaded_attachments, many=True, context={'request': request}).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class ProjectProgressView(APIView):
    """Quick progress summary for a project"""
    workspace_module = 'projects'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, project_id):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        total = project.tasks.count()
        done  = project.tasks.filter(status='Done').count()
        return Response({
            'total_tasks':     total,
            'completed_tasks': done,
            'progress':        round((done / total) * 100) if total else 0,
            'feature_count':   project.features.count(),
        })


class MyTasksView(APIView):
    """Get tasks based on user role - Admin/Manager see all, others see assigned"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        user = request.user
        
        if user.role == 'admin':
            tasks = Task.objects.filter(project__workspace_id=user.workspace_id).select_related(
                'project', 'feature', 'assignee', 'reporter'
            ).prefetch_related('project__client', 'comments__author').order_by('-created_at')
        elif user.role == 'manager':
            user_projects = projects_for_user(user)
            tasks = Task.objects.filter(project__in=user_projects).select_related(
                'project', 'feature', 'assignee', 'reporter'
            ).prefetch_related('project__client', 'comments__author').order_by('-created_at')
        elif user.role == 'qa_tester':
            # Tester sees: Testing status tasks in their projects OR directly assigned to them
            user_projects = projects_for_user(user)
            tasks = Task.objects.filter(
                Q(project__in=user_projects, status='Testing') | Q(assignee=user)
            ).distinct().select_related(
                'project', 'feature', 'assignee', 'reporter'
            ).prefetch_related('project__client', 'comments__author').order_by('-created_at')
        else:
            tasks = Task.objects.filter(assignee=user).exclude(status='Testing').select_related(
                'project', 'feature', 'assignee', 'reporter'
            ).prefetch_related('project__client', 'comments__author').order_by('-created_at')
        
        # Add project_name and project_id fields for compatibility with frontend
        task_data = []
        for task in tasks:
            task_dict = TaskSerializer(task).data
            task_dict['project_name'] = task.project.name
            task_dict['project_id'] = task.project.id  # Add project_id for filtering
            task_dict['issue_type'] = 'task'  # Set default type for tasks
            task_data.append(task_dict)
        
        # Also fetch subtasks assigned to the user that their parent task is not already assigned to them
        if user.role == 'admin':
            subtasks = SubTask.objects.filter(task__project__workspace_id=user.workspace_id).select_related(
                'task__project', 'assignee', 'created_by', 'task__feature'
            ).prefetch_related('task__comments__author').order_by('-created_at')
        elif user.role == 'manager':
            user_projects = projects_for_user(user)
            subtasks = SubTask.objects.filter(
                task__project__in=user_projects
            ).select_related(
                'task__project', 'assignee', 'created_by', 'task__feature'
            ).prefetch_related('task__comments__author').order_by('-created_at')
        elif user.role == 'qa_tester':
            user_projects = projects_for_user(user)
            subtasks = SubTask.objects.filter(
                (Q(task__project__in=user_projects, status='Testing')) | 
                Q(assignee=user) | 
                (Q(task__assignee=user) & ~Q(status='Testing'))
            ).distinct().select_related(
                'task__project', 'assignee', 'created_by', 'task__feature'
            ).prefetch_related('task__comments__author').order_by('-created_at')
        else:
            subtasks = SubTask.objects.filter(
                (Q(assignee=user) | Q(task__assignee=user)) & ~Q(status='Testing')
            ).distinct().select_related(
                'task__project', 'assignee', 'created_by', 'task__feature'
            ).prefetch_related('task__comments__author').order_by('-created_at')
        
        # Add subtasks to the response
        for subtask in subtasks:
            subtask_dict = SubTaskSerializer(subtask).data
            subtask_dict['project'] = subtask.task.project.id
            subtask_dict['project_name'] = subtask.task.project.name
            subtask_dict['project_id'] = subtask.task.project.id
            subtask_dict['issue_type'] = 'subtask'
            subtask_dict['itemType'] = 'subtask'  # Frontend expects itemType
            subtask_dict['parent_task_id'] = subtask.task.id
            subtask_dict['task_id'] = subtask.task.task_id  # String ID like "YOJAK-T1" for comment API
            subtask_dict['parent_task_title'] = subtask.task.title
            # Include parent task's comments (since subtask comments are posted to parent task)
            subtask_dict['comments'] = TaskCommentSerializer(subtask.task.comments.all(), many=True, context={'request': request}).data
            task_data.append(subtask_dict)
        
        return Response(task_data)


# ─── Module Views ─────────────────────────────────────────────────────────────

class ModuleListCreateView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, project_slug):
        try:
            project = Project.objects.get(slug=project_slug)
        except Project.DoesNotExist:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        modules = Module.objects.filter(project=project).select_related('created_by', 'owner')
        return Response(ModuleSerializer(modules, many=True).data)

    def post(self, request, project_slug):
        try:
            project = Project.objects.get(slug=project_slug)
        except Project.DoesNotExist:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Only admin/manager can create modules
        user = request.user
        is_manager = project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Only admin or manager can create modules'}, status=status.HTTP_403_FORBIDDEN)
        
        data = request.data.copy()
        data['project'] = project.id
        serializer = ModuleWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        module = serializer.save(created_by=request.user)
        log_activity(request.user, 'module_created', module.title, project=project,
                     extra={'module_id': module.module_id})
        return Response(ModuleSerializer(module).data, status=status.HTTP_201_CREATED)


def _get_module(project, module_id):
    """Get module by module_id (e.g. YOJAK-M01)"""
    return Module.objects.get(project=project, module_id__iexact=module_id)


class ModuleFeatureListCreateView(APIView):
    """Features within a module"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, project_slug, module_slug):
        try:
            project = Project.objects.get(slug=project_slug)
            module = _get_module(project, module_slug)
        except (Project.DoesNotExist, Module.DoesNotExist):
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        features = Feature.objects.filter(module=module).select_related('assignee', 'reporter', 'module').prefetch_related('tasks')
        return Response(FeatureSerializer(features, many=True).data)

    def post(self, request, project_slug, module_slug):
        try:
            project = Project.objects.get(slug=project_slug)
            module = _get_module(project, module_slug)
        except (Project.DoesNotExist, Module.DoesNotExist):
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Only admin/manager can create features
        user = request.user
        is_manager = module.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Only admin or manager can create features'}, status=status.HTTP_403_FORBIDDEN)
        
        data = request.data.copy()
        data['project'] = project.id
        data['module'] = module.id
        serializer = FeatureWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        feature = serializer.save(reporter=request.user)
        log_activity(request.user, 'feature_created', feature.title, project=project,
                     extra={'feature_id': feature.feature_id, 'module_id': module.module_id})
        return Response(FeatureSerializer(feature).data, status=status.HTTP_201_CREATED)


class ModuleTaskListCreateView(APIView):
    """Direct tasks in module (when no features)"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request, project_slug, module_slug):
        try:
            project = Project.objects.get(slug=project_slug)
            module = _get_module(project, module_slug)
        except (Project.DoesNotExist, Module.DoesNotExist):
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        tasks = Task.objects.filter(module=module, feature__isnull=True).select_related('assignee', 'reporter')
        return Response(TaskSerializer(tasks, many=True).data)

    def post(self, request, project_slug, module_slug):
        try:
            project = Project.objects.get(slug=project_slug)
            module = _get_module(project, module_slug)
        except (Project.DoesNotExist, Module.DoesNotExist):
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Only admin/manager can create tasks
        user = request.user
        is_manager = module.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Only admin or manager can create tasks'}, status=status.HTTP_403_FORBIDDEN)
        
        data = request.data.copy()
        data['project'] = project.id
        data['module'] = module.id
        if not data.get('assignee') and module.owner_id:
            data['assignee'] = module.owner_id
        # Remove feature key entirely so it stays null
        data.pop('feature', None)
        
        serializer = TaskWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(reporter=request.user, feature=None)
        log_activity(request.user, 'task_created', task.title, project=project,
                     extra={'task_id': task.task_id, 'module_id': module.module_id})
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


class FeatureTaskCreateView(APIView):
    """Create task directly under a feature (feature_id set, module_id from feature)"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def post(self, request, project_slug, module_slug, feature_db_id):
        try:
            project = Project.objects.get(slug=project_slug)
            module = _get_module(project, module_slug)
            feature = Feature.objects.get(id=feature_db_id, module=module)
        except (Project.DoesNotExist, Module.DoesNotExist, Feature.DoesNotExist):
            return Response({'error': 'Feature not found'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_manager = project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['feature'] = feature.id
        data['module'] = module.id
        data['project'] = project.id
        if not data.get('assignee') and feature.assignee_id:
            data['assignee'] = feature.assignee_id
        serializer = TaskWriteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(reporter=request.user)
        log_activity(request.user, 'task_created', task.title, project=project,
                     extra={'task_id': task.task_id, 'feature_id': feature.feature_id, 'module_id': module.module_id})
        if task.assignee_id and not feature.assignee_id:
            feature.assignee = task.assignee
            feature.save(update_fields=['assignee'])
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


class ModuleDetailView(APIView):
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get_object(self, project_slug, module_id):
        try:
            project = Project.objects.get(slug=project_slug)
            return Module.objects.select_related('project', 'created_by', 'owner').get(
                project=project, module_id__iexact=module_id
            )
        except (Project.DoesNotExist, Module.DoesNotExist):
            return None

    def get(self, request, project_slug, module_slug):
        module = self.get_object(project_slug, module_slug)
        if not module:
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, module.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return Response(ModuleSerializer(module).data)

    def patch(self, request, project_slug, module_slug):
        module = self.get_object(project_slug, module_slug)
        if not module:
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = module.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ModuleWriteSerializer(module, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_activity(request.user, 'module_updated', module.title, project=module.project,
                     extra={'module_id': module.module_id})
        return Response(ModuleSerializer(module).data)

    def delete(self, request, project_slug, module_slug):
        module = self.get_object(project_slug, module_slug)
        if not module:
            return Response({'error': 'Module not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = module.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        title = module.title
        project = module.project
        module_key = module.module_id
        module.delete()
        log_activity(request.user, 'module_deleted', title, project=project,
                     extra={'module_id': module_key})
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmployeeTasksView(APIView):
    """Get employee's assigned tasks"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def get(self, request):
        user = request.user
        tasks = Task.objects.filter(assignee=user).select_related(
            'project', 'feature', 'module'
        )
        task_data = []
        for task in tasks:
            task_dict = TaskSerializer(task).data
            task_dict['project_name'] = task.project.name
            task_data.append(task_dict)
        return Response(task_data)


# ─── SubTask Views ────────────────────────────────────────────────────────────

class SubTaskListCreateView(APIView):
    """List and create subtasks for a task"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def _get_task(self, task_id):
        try:
            return Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return None

    def get(self, request, task_id):
        task = self._get_task(task_id)
        if not task:
            return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, task.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        subtasks = task.subtasks.select_related('assignee', 'created_by')
        return Response(SubTaskSerializer(subtasks, many=True).data)

    def post(self, request, task_id):
        task = self._get_task(task_id)
        if not task:
            return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, task.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        user = request.user
        is_manager = task.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Only admin or manager can create subtasks'}, status=status.HTTP_403_FORBIDDEN)
        serializer = SubTaskWriteSerializer(data=request.data, context={'task': task})
        serializer.is_valid(raise_exception=True)
        subtask = serializer.save(task=task, created_by=request.user)
        log_activity(request.user, 'subtask_created', subtask.title, project=task.project,
                     extra={'subtask_id': subtask.subtask_id, 'task_id': task.task_id})
        # Signals will automatically send notification when subtask is saved with assignee
        return Response(SubTaskSerializer(subtask).data, status=status.HTTP_201_CREATED)


class SubTaskDetailView(APIView):
    """Retrieve, update, delete a subtask"""
    workspace_module = 'tasks'
    permission_classes = [IsAuthenticated, WorkspaceModuleAccess]

    def _get_subtask(self, subtask_id):
        try:
            return SubTask.objects.select_related('task__project', 'assignee', 'created_by').get(id=subtask_id)
        except SubTask.DoesNotExist:
            return None

    def get(self, request, subtask_id):
        subtask = self._get_subtask(subtask_id)
        if not subtask:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not user_can_access_project(request.user, subtask.task.project):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return Response(SubTaskSerializer(subtask).data)

    def patch(self, request, subtask_id):
        subtask = self._get_subtask(subtask_id)
        if not subtask:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = subtask.task.project.team_members.filter(user=user, project_role='manager').exists()
        is_assignee = subtask.assignee == user
        updating_only_status = list(request.data.keys()) == ['status']
        if not (user.role == 'admin' or is_manager or (is_assignee and updating_only_status)):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = SubTaskWriteSerializer(subtask, data=request.data, partial=True, context={'task': subtask.task})
        serializer.is_valid(raise_exception=True)
        old_status = subtask.status
        serializer.save()
        subtask.refresh_from_db()
        if subtask.status != old_status:
            log_activity(request.user, 'status_changed', subtask.title, project=subtask.task.project,
                         extra={'from': old_status, 'to': subtask.status, 'subtask_id': subtask.subtask_id, 'task_id': subtask.task.task_id})
        else:
            log_activity(request.user, 'subtask_updated', subtask.title, project=subtask.task.project,
                         extra={'subtask_id': subtask.subtask_id, 'task_id': subtask.task.task_id})
        # Signals will automatically send notifications when subtask is saved with assignee or status changes
        return Response(SubTaskSerializer(subtask).data)

    def delete(self, request, subtask_id):
        subtask = self._get_subtask(subtask_id)
        if not subtask:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        is_manager = subtask.task.project.team_members.filter(user=user, project_role='manager').exists()
        if user.role != 'admin' and not is_manager:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        title = subtask.title
        project = subtask.task.project
        subtask_key = subtask.subtask_id
        task_key = subtask.task.task_id
        subtask.delete()
        log_activity(request.user, 'subtask_deleted', title, project=project,
                     extra={'subtask_id': subtask_key, 'task_id': task_key})
        return Response(status=status.HTTP_204_NO_CONTENT)
