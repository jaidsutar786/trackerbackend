from django.urls import path
from .views import (
    ClientListCreateView, ClientDetailView, ClientProjectsView,
    ProjectListCreateView, ProjectDetailView, DashboardStatsView, WorkOverviewView,
    AnalyticsReportView, AnalyticsExportView,
    IssueListCreateView, IssueDetailView, IssueCommentView, CommentLikeView,
    ActivityLogListView,
    FeatureListCreateView, FeatureDetailView,
    TaskListCreateView, TaskDetailView, TaskCommentView,
    ProjectProgressView, MyTasksView,
    ModuleListCreateView, ModuleDetailView, ModuleFeatureListCreateView, ModuleTaskListCreateView,
    EmployeeTasksView, FeatureTaskCreateView,
    SubTaskListCreateView, SubTaskDetailView,
)

urlpatterns = [
    # Clients
    path('clients/', ClientListCreateView.as_view(), name='client-list-create'),
    path('clients/<int:pk>/', ClientDetailView.as_view(), name='client-detail'),
    path('clients/<int:pk>/projects/', ClientProjectsView.as_view(), name='client-projects'),

    # Stats, Issues, Activity Logs (must come before slug patterns)
    path('dashboard-stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    path('work-overview/', WorkOverviewView.as_view(), name='work-overview'),
    path('analytics/summary/', AnalyticsReportView.as_view(), name='analytics-summary'),
    path('analytics/export.csv', AnalyticsExportView.as_view(), name='analytics-export'),
    path('issues/', IssueListCreateView.as_view(), name='issue-list-create'),
    path('issues/<int:pk>/', IssueDetailView.as_view(), name='issue-detail'),
    path('issues/<int:issue_id>/comments/', IssueCommentView.as_view(), name='issue-comment'),
    path('comments/<int:comment_id>/like/', CommentLikeView.as_view(), name='comment-like'),
    path('activity-logs/', ActivityLogListView.as_view(), name='activity-logs'),

    # Employee Tasks - Direct access for assigned tasks
    path('tasks/my-tasks/', MyTasksView.as_view(), name='my-tasks'),
    path('employee/my-tasks/', EmployeeTasksView.as_view(), name='employee-tasks'),

    # Projects (numeric ID patterns first)
    path('', ProjectListCreateView.as_view(), name='project-list-create'),
    path('<int:pk>/', ProjectDetailView.as_view(), name='project-detail'),
    path('<int:project_id>/progress/', ProjectProgressView.as_view(), name='project-progress'),

    # Features (Epics) — nested under project (numeric ID patterns)
    path('<int:project_id>/features/', FeatureListCreateView.as_view(), name='feature-list-create'),
    path('<int:project_id>/features/<str:feature_id>/', FeatureDetailView.as_view(), name='feature-detail'),

    # Tasks — nested under project + feature (numeric ID patterns)
    path('<int:project_id>/features/<str:feature_id>/tasks/', TaskListCreateView.as_view(), name='task-list-create'),
    path('<int:project_id>/tasks/<str:task_id>/', TaskDetailView.as_view(), name='task-detail'),
    path('<int:project_id>/tasks/<int:task_id>/', TaskDetailView.as_view(), name='task-detail-by-id'),
    path('<int:project_id>/tasks/<str:task_id>/comments/', TaskCommentView.as_view(), name='task-comment'),

    # Slug-based patterns (must come after all other patterns)
    path('<slug:project_slug>/modules/', ModuleListCreateView.as_view(), name='module-list-create'),
    path('<slug:project_slug>/modules/<str:module_slug>/', ModuleDetailView.as_view(), name='module-detail'),
    path('<slug:project_slug>/modules/<str:module_slug>/features/', ModuleFeatureListCreateView.as_view(), name='module-feature-list'),
    path('<slug:project_slug>/modules/<str:module_slug>/tasks/', ModuleTaskListCreateView.as_view(), name='module-task-list'),
    path('<slug:project_slug>/features/<str:feature_id>/', FeatureDetailView.as_view(), name='feature-detail-by-slug'),
    path('<slug:project_slug>/tasks/<str:task_id>/', TaskDetailView.as_view(), name='task-detail-by-slug'),
    path('<slug:project_slug>/tasks/<str:task_id>/comments/', TaskCommentView.as_view(), name='task-comment-by-slug'),
    path('<slug:project_slug>/modules/<str:module_slug>/features/<int:feature_db_id>/tasks/', FeatureTaskCreateView.as_view(), name='feature-task-create'),
    path('<slug:project_slug>/features/<str:feature_id>/tasks/', TaskListCreateView.as_view(), name='task-list-create-by-slug'),
    
    # SubTasks
    path('tasks/<int:task_id>/subtasks/', SubTaskListCreateView.as_view(), name='subtask-list-create'),
    path('subtasks/<int:subtask_id>/', SubTaskDetailView.as_view(), name='subtask-detail'),

    # Project by slug (must be last)
    path('<slug:slug>/', ProjectDetailView.as_view(), name='project-detail-by-slug'),
]
