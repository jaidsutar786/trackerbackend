import csv
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.db import connection
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from projects.models import Client, Project, ProjectMember, Task


class TaskLifecycleTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='analytics-user',
			email='analytics@example.com',
			password='test-password',
		)
		client = Client.objects.create(name='Analytics Client', created_by=self.user)
		self.project = Project.objects.create(client=client, name='Analytics Project')

	def test_task_lifecycle_timestamps_track_status_transitions(self):
		task = Task.objects.create(
			project=self.project,
			title='Measure delivery time',
			reporter=self.user,
		)

		task.status = 'In Progress'
		task.save(update_fields=['status'])
		task.refresh_from_db()
		self.assertIsNotNone(task.started_at)
		self.assertIsNone(task.completed_at)

		task.status = 'Done'
		task.save(update_fields=['status'])
		task.refresh_from_db()
		completed_at = task.completed_at
		self.assertIsNotNone(completed_at)

		task.title = 'Updated after completion'
		task.save(update_fields=['title'])
		task.refresh_from_db()
		self.assertEqual(task.completed_at, completed_at)

		task.status = 'To Do'
		task.save(update_fields=['status'])
		task.refresh_from_db()
		self.assertIsNone(task.completed_at)


class AnalyticsReportTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user(
			username='analytics-admin',
			email='analytics-admin@example.com',
			password='test-password',
			role='admin',
		)
		self.client_user = User.objects.create_user(
			username='analytics-client',
			email='analytics-client@example.com',
			password='test-password',
			role='client',
		)
		self.client_record = Client.objects.create(name='Analytics Client', created_by=self.admin)
		self.client_record.users.add(self.client_user)
		self.project = Project.objects.create(
			client=self.client_record,
			name='Visible Analytics Project',
		)
		self.open_task = Task.objects.create(
			project=self.project,
			title='=SUM(1,2)',
			status='To Do',
			due_date=timezone.localdate() - timedelta(days=1),
			estimate_hours=Decimal('3.00'),
		)
		completed_task = Task.objects.create(
			project=self.project,
			title='Completed delivery',
			status='In Progress',
		)
		completed_task.status = 'Done'
		completed_task.save(update_fields=['status'])

		self.api_client = APIClient()

	def test_summary_returns_trends_workload_and_real_delivery_metrics(self):
		self.api_client.force_authenticate(user=self.admin)

		response = self.api_client.get('/api/projects/analytics/summary/?days=30')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['summary']['total_tasks'], 2)
		self.assertEqual(response.data['summary']['completed_tasks'], 1)
		self.assertEqual(response.data['summary']['overdue_tasks'], 1)
		self.assertIsNotNone(response.data['summary']['lead_time_avg_days'])
		self.assertIsNotNone(response.data['summary']['cycle_time_avg_days'])
		self.assertEqual(len(response.data['trend']), 30)
		self.assertEqual(response.data['workload'][0]['estimate_hours'], 3.0)
		self.assertEqual(response.data['projects'][0]['project_id'], self.project.id)

	def test_summary_uses_scoped_short_lived_cache(self):
		cache.clear()
		self.api_client.force_authenticate(user=self.admin)
		with CaptureQueriesContext(connection) as first_request_queries:
			first_response = self.api_client.get('/api/projects/analytics/summary/?days=30')
		with CaptureQueriesContext(connection) as cached_request_queries:
			second_response = self.api_client.get('/api/projects/analytics/summary/?days=30')

		self.assertEqual(first_response.status_code, 200)
		self.assertEqual(second_response.data, first_response.data)
		self.assertLess(len(cached_request_queries), len(first_request_queries))

	def test_client_summary_and_csv_are_limited_to_visible_projects(self):
		self.project.name = '=Visible Analytics Project'
		self.project.save(update_fields=['name'])
		unrelated_client = Client.objects.create(name='Unrelated Client', created_by=self.admin)
		unrelated_project = Project.objects.create(
			client=unrelated_client,
			name='Private Analytics Project',
		)
		Task.objects.create(project=unrelated_project, title='Private task')
		self.api_client.force_authenticate(user=self.client_user)

		summary = self.api_client.get('/api/projects/analytics/summary/')
		export = self.api_client.get('/api/projects/analytics/export.csv')

		self.assertEqual(summary.status_code, 200)
		self.assertEqual([row['project_id'] for row in summary.data['projects']], [self.project.id])
		self.assertEqual(summary.data['workload'], [])
		self.assertEqual(export.status_code, 200)
		rows = list(csv.reader(StringIO(export.content.decode('utf-8'))))
		self.assertEqual(len(rows), 2)
		self.assertIn("'=Visible Analytics Project", export.content.decode('utf-8'))
		self.assertNotIn('Private Analytics Project', export.content.decode('utf-8'))
		self.assertNotIn('Completed delivery', export.content.decode('utf-8'))

	def test_admin_csv_escapes_spreadsheet_formulas(self):
		self.api_client.force_authenticate(user=self.admin)

		response = self.api_client.get('/api/projects/analytics/export.csv')
		rows = list(csv.reader(StringIO(response.content.decode('utf-8'))))

		self.assertTrue(any(row[3].startswith("'=SUM") for row in rows[1:]))

	def test_invalid_period_is_rejected(self):
		self.api_client.force_authenticate(user=self.admin)

		response = self.api_client.get('/api/projects/analytics/summary/?days=14')

		self.assertEqual(response.status_code, 400)


class WorkspaceProjectIsolationTests(TestCase):
	def setUp(self):
		from accounts.models import Workspace

		self.workspace = Workspace.objects.create(name='Workspace One', slug='workspace-one')
		self.other_workspace = Workspace.objects.create(name='Workspace Two', slug='workspace-two')
		self.admin = User.objects.create_user(
			username='workspace-one-admin',
			email='workspace-one-admin@example.com',
			password='test-password',
			role='admin',
			workspace=self.workspace,
		)
		self.other_admin = User.objects.create_user(
			username='workspace-two-admin',
			email='workspace-two-admin@example.com',
			password='test-password',
			role='admin',
			workspace=self.other_workspace,
		)
		self.client_record = Client.objects.create(
			name='Workspace One Client',
			created_by=self.admin,
			workspace=self.workspace,
		)
		self.other_client_record = Client.objects.create(
			name='Workspace Two Client',
			created_by=self.other_admin,
			workspace=self.other_workspace,
		)
		self.project = Project.objects.create(
			client=self.other_client_record,
			name='Private Workspace Project',
		)
		self.api_client = APIClient()
		self.api_client.force_authenticate(user=self.admin)

	def test_project_list_and_detail_are_workspace_scoped(self):
		list_response = self.api_client.get('/api/projects/')
		detail_response = self.api_client.get(f'/api/projects/{self.project.pk}/')

		self.assertEqual(list_response.status_code, 200)
		self.assertEqual(list_response.data, [])
		self.assertEqual(detail_response.status_code, 404)

	def test_project_list_query_count_stays_bounded_as_projects_grow(self):
		for index in range(4):
			client_user = User.objects.create_user(
				username=f'visible-client-{index}',
				email=f'visible-client-{index}@example.com',
				password='test-password',
				role='client',
				workspace=self.workspace,
			)
			client = Client.objects.create(
				name=f'Visible Client {index}',
				created_by=self.admin,
				workspace=self.workspace,
			)
			client.users.add(client_user)
			project = Project.objects.create(client=client, name=f'Visible Project {index}')
			ProjectMember.objects.create(project=project, user=self.admin, project_role='manager')

		with CaptureQueriesContext(connection) as captured_queries:
			response = self.api_client.get('/api/projects/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.data), 4)
		self.assertLessEqual(len(captured_queries), 12)

	def test_project_creation_rejects_a_client_from_another_workspace(self):
		response = self.api_client.post('/api/projects/', {
			'client': self.other_client_record.pk,
			'name': 'Cross Workspace Project',
		}, format='json')

		self.assertEqual(response.status_code, 400)
		self.assertFalse(Project.objects.filter(name='Cross Workspace Project').exists())

	def test_project_limit_is_enforced_before_creation(self):
		for index in range(self.workspace.project_limit):
			Project.objects.create(
				client=self.client_record,
				name=f'Existing project {index}',
			)

		response = self.api_client.post('/api/projects/', {
			'client': self.client_record.pk,
			'name': 'Over limit project',
		}, format='json')

		self.assertEqual(response.status_code, 409)
		self.assertFalse(Project.objects.filter(name='Over limit project').exists())
