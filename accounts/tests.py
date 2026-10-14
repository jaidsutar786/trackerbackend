from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .billing import handle_stripe_event
from .models import User, Workspace


class WorkspacePlanTests(TestCase):
	def test_plan_limits_are_server_defined(self):
		self.assertEqual(Workspace(plan='free').seat_limit, 5)
		self.assertEqual(Workspace(plan='free').project_limit, 3)
		self.assertEqual(Workspace(plan='trial').seat_limit, 10)
		self.assertEqual(Workspace(plan='paid').project_limit, 100)

	def test_expired_trial_uses_free_plan_limits(self):
		workspace = Workspace(
			plan='trial',
			subscription_status='trialing',
			trial_ends_at=timezone.now() - timedelta(seconds=1),
		)

		self.assertEqual(workspace.effective_plan, 'free')
		self.assertEqual(workspace.seat_limit, 5)
		self.assertEqual(workspace.project_limit, 3)


class WorkspaceAccountAPITests(TestCase):
	def setUp(self):
		self.workspace = Workspace.objects.create(
			name='Test Workspace',
			slug='test-workspace',
		)
		self.admin = User.objects.create_user(
			username='workspace-admin',
			email='workspace-admin@example.com',
			password='test-password',
			role='admin',
			workspace=self.workspace,
		)
		self.api_client = APIClient()
		self.api_client.force_authenticate(user=self.admin)

	def test_usage_reports_plan_limits(self):
		response = self.api_client.get('/api/auth/workspace/usage/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['seats'], {'used': 1, 'limit': 5})
		self.assertEqual(response.data['projects'], {'used': 0, 'limit': 3})
		self.assertTrue(response.data['can_add_seat'])

	def test_invite_is_rejected_when_workspace_is_at_seat_limit(self):
		for index in range(4):
			User.objects.create_user(
				username=f'workspace-user-{index}',
				email=f'workspace-user-{index}@example.com',
				password='test-password',
				workspace=self.workspace,
			)

		response = self.api_client.post('/api/auth/users/', {
			'email': 'seat-limit@example.com',
			'role': 'frontend_developer',
		})

		self.assertEqual(response.status_code, 409)
		self.assertEqual(self.workspace.users.count(), self.workspace.seat_limit)

	def test_workspace_settings_update_does_not_allow_self_service_plan_change(self):
		response = self.api_client.patch('/api/auth/workspace/', {
			'name': 'Renamed Workspace',
			'billing_email': 'billing@example.com',
			'plan': 'paid',
		}, format='json')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['name'], 'Renamed Workspace')
		self.assertEqual(response.data['billing_email'], 'billing@example.com')
		self.assertEqual(response.data['plan'], 'free')

	def test_admin_cannot_read_another_workspace_user_profile(self):
		other_workspace = Workspace.objects.create(
			name='Other Workspace',
			slug='other-workspace',
		)
		other_user = User.objects.create_user(
			username='other-admin',
			email='other-admin@example.com',
			password='test-password',
			role='admin',
			workspace=other_workspace,
		)

		response = self.api_client.get(f'/api/auth/users/{other_user.pk}/')

		self.assertEqual(response.status_code, 404)

	def test_workspace_role_override_is_enforced_on_reports_api(self):
		manager = User.objects.create_user(
			username='workspace-manager',
			email='workspace-manager@example.com',
			password='test-password',
			role='manager',
			workspace=self.workspace,
		)
		settings_response = self.api_client.patch('/api/auth/workspace/', {
			'role_permissions': {
				'manager': {'reports': False, 'clients': False, 'settings': True},
			},
		}, format='json')
		self.assertEqual(settings_response.status_code, 200)
		self.assertFalse(settings_response.data['role_permissions']['manager']['reports'])
		self.assertFalse(settings_response.data['role_permissions']['manager']['clients'])
		self.assertTrue(settings_response.data['role_permissions']['manager']['settings'])
		self.assertTrue(settings_response.data['default_role_permissions']['manager']['reports'])
		self.assertTrue(settings_response.data['default_role_permissions']['manager']['clients'])
		self.assertFalse(settings_response.data['default_role_permissions']['manager']['settings'])
		self.assertFalse(settings_response.data['effective_role_permissions']['manager']['reports'])
		self.assertFalse(settings_response.data['effective_role_permissions']['manager']['clients'])
		self.assertTrue(settings_response.data['effective_role_permissions']['manager']['settings'])

		self.api_client.force_authenticate(user=manager)
		current_user = self.api_client.get('/api/auth/me/')
		response = self.api_client.get('/api/projects/analytics/summary/')

		self.assertFalse(current_user.data['workspace_permissions']['reports'])
		self.assertFalse(current_user.data['workspace_permissions']['clients'])
		self.assertTrue(current_user.data['workspace_permissions']['settings'])
		self.assertEqual(response.status_code, 403)
		self.assertEqual(self.api_client.get('/api/projects/clients/').status_code, 403)
		self.assertEqual(self.api_client.get('/api/auth/workspace/').status_code, 200)

	def test_workspace_admin_permissions_cannot_be_customized(self):
		response = self.api_client.patch('/api/auth/workspace/', {
			'role_permissions': {'admin': {'reports': False}},
		}, format='json')

		self.assertEqual(response.status_code, 400)


class WorkspaceBillingTests(TestCase):
	def setUp(self):
		self.workspace = Workspace.objects.create(
			name='Billing Workspace',
			slug='billing-workspace',
			billing_email='billing@example.com',
		)
		self.admin = User.objects.create_user(
			username='billing-admin',
			email='billing-admin@example.com',
			password='test-password',
			role='admin',
			workspace=self.workspace,
		)
		self.api_client = APIClient()
		self.api_client.force_authenticate(user=self.admin)

	def test_admin_can_start_one_fourteen_day_trial(self):
		response = self.api_client.post('/api/auth/workspace/trial/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['plan'], 'trial')
		self.assertGreater(response.data['trial_ends_at'], timezone.now())
		self.assertEqual(response.data['seat_limit'], 10)
		self.assertEqual(self.workspace.__class__.objects.get(pk=self.workspace.pk).plan, 'trial')

	@override_settings(STRIPE_SECRET_KEY='sk_test_value', STRIPE_PRICE_PAID='price_test_value')
	@patch('accounts.billing.stripe.checkout.Session.create')
	@patch('accounts.billing.stripe.Customer.create')
	def test_checkout_creates_customer_and_returns_checkout_url(self, customer_create, session_create):
		customer_create.return_value = Mock(id='cus_workspace')
		session_create.return_value = Mock(url='https://checkout.example/session')

		response = self.api_client.post('/api/auth/workspace/billing/checkout/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['url'], 'https://checkout.example/session')
		self.workspace.refresh_from_db()
		self.assertEqual(self.workspace.billing_customer_id, 'cus_workspace')

	def test_checkout_is_disabled_when_stripe_is_not_configured(self):
		response = self.api_client.post('/api/auth/workspace/billing/checkout/')

		self.assertEqual(response.status_code, 503)

	def test_subscription_webhook_updates_plan_and_period(self):
		period_end = int((timezone.now() + timedelta(days=30)).timestamp())
		handle_stripe_event({
			'type': 'customer.subscription.updated',
			'data': {'object': {
				'id': 'sub_workspace',
				'customer': None,
				'metadata': {'workspace_id': str(self.workspace.pk)},
				'status': 'active',
				'current_period_end': period_end,
			}},
		})

		self.workspace.refresh_from_db()
		self.assertEqual(self.workspace.plan, 'paid')
		self.assertEqual(self.workspace.subscription_status, 'active')
		self.assertEqual(self.workspace.billing_subscription_id, 'sub_workspace')
		self.assertEqual(int(self.workspace.current_period_end.timestamp()), period_end)
