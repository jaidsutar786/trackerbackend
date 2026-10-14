from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from notifications.management.commands.send_notification_digests import Command
from notifications.checks import check_production_channel_layer
from .models import NotificationPreference


class NotificationPreferenceTests(SimpleTestCase):
    def test_in_app_preference_allows_notification(self):
        preference = NotificationPreference(in_app_enabled=True)

        self.assertTrue(preference.allows('task_assigned'))

    def test_email_digest_allows_notification_without_in_app_delivery(self):
        preference = NotificationPreference(
            in_app_enabled=False,
            email_enabled=True,
            email_digest='daily',
        )

        self.assertTrue(preference.allows('task_assigned'))

    def test_disabled_delivery_channels_reject_notification(self):
        preference = NotificationPreference(
            in_app_enabled=False,
            email_enabled=False,
            email_digest='daily',
        )

        self.assertFalse(preference.allows('task_assigned'))


class NotificationChannelLayerCheckTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        CHANNEL_LAYERS={
            'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
        },
    )
    def test_production_warns_when_redis_is_not_configured(self):
        messages = check_production_channel_layer(None)

        self.assertEqual([message.id for message in messages], ['notifications.W001'])

    @override_settings(
        DEBUG=False,
        CHANNEL_LAYERS={
            'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer'},
        },
    )
    def test_production_accepts_redis_channel_layer(self):
        self.assertEqual(check_production_channel_layer(None), [])

    def test_muted_notification_type_is_rejected(self):
        preference = NotificationPreference(
            in_app_enabled=True,
            muted_types=['task_assigned'],
        )

        self.assertFalse(preference.allows('task_assigned'))


class NotificationDigestCommandTests(SimpleTestCase):
    @patch('notifications.management.commands.send_notification_digests.send_mail')
    @patch('notifications.management.commands.send_notification_digests.Notification.objects')
    @patch('notifications.management.commands.send_notification_digests.NotificationPreference.objects')
    def test_successful_digest_records_checkpoint_and_uses_it_next_run(
        self,
        preference_manager,
        notification_manager,
        send_mail_mock,
    ):
        sent_at = timezone.now() - timedelta(hours=2)
        preference = Mock()
        preference.user.pk = 42
        preference.user.email = 'user@example.com'
        preference.user.username = 'user'
        preference.user.get_full_name.return_value = ''
        preference.daily_digest_sent_at = sent_at
        preference.daily_digest_last_notification_id = 3
        preference_manager.filter.return_value.select_related.return_value = [preference]

        notification = Mock(pk=4, title='Task assigned', message='You have a task.')
        notification_manager.filter.return_value.order_by.return_value.__getitem__.return_value = [notification]
        send_mail_mock.return_value = 1

        call_command('send_notification_digests', frequency='daily', stdout=Mock())

        notification_manager.filter.assert_called_once_with(
            recipient=preference.user,
            read=False,
            pk__gt=3,
        )
        send_mail_mock.assert_called_once()
        preference.save.assert_called_once_with(
            update_fields=[
                'daily_digest_sent_at',
                'daily_digest_last_notification_id',
                'updated_at',
            ]
        )
        self.assertGreaterEqual(preference.daily_digest_sent_at, sent_at)
        self.assertEqual(preference.daily_digest_last_notification_id, 4)

    @patch('notifications.management.commands.send_notification_digests.send_mail')
    @patch('notifications.management.commands.send_notification_digests.Notification.objects')
    @patch('notifications.management.commands.send_notification_digests.NotificationPreference.objects')
    def test_email_failure_does_not_stop_other_recipients(
        self,
        preference_manager,
        notification_manager,
        send_mail_mock,
    ):
        preferences = []
        for user_id in (1, 2):
            preference = Mock()
            preference.user.pk = user_id
            preference.user.email = f'user{user_id}@example.com'
            preference.user.username = f'user{user_id}'
            preference.user.get_full_name.return_value = ''
            preference.daily_digest_sent_at = None
            preferences.append(preference)
        preference_manager.filter.return_value.select_related.return_value = preferences

        notification_query = MagicMock()
        notification_query.order_by.return_value.__getitem__.return_value = [
            Mock(pk=7, title='Task assigned', message='You have a task.'),
        ]
        notification_manager.filter.return_value = notification_query
        send_mail_mock.side_effect = [OSError('SMTP unavailable'), 1]

        with self.assertLogs(
            'notifications.management.commands.send_notification_digests',
            level='ERROR',
        ):
            call_command('send_notification_digests', frequency='daily', stdout=Mock())

        self.assertEqual(send_mail_mock.call_count, 2)
        preferences[0].save.assert_not_called()
        preferences[1].save.assert_called_once_with(
            update_fields=[
                'daily_digest_sent_at',
                'daily_digest_last_notification_id',
                'updated_at',
            ]
        )
        self.assertEqual(preferences[1].daily_digest_last_notification_id, 7)