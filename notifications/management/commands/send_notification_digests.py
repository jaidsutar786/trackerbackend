import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Notification, NotificationPreference


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send daily or weekly unread notification digest emails.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--frequency',
            choices=['daily', 'weekly'],
            default='daily',
            help='Digest frequency to send.',
        )

    def handle(self, *args, **options):
        frequency = options['frequency']
        sent_at_field = f'{frequency}_digest_sent_at'
        cursor_field = f'{frequency}_digest_last_notification_id'
        preferences = NotificationPreference.objects.filter(
            email_enabled=True,
            email_digest=frequency,
            user__email__isnull=False,
        ).select_related('user')

        sent_count = 0
        failed_count = 0
        for preference in preferences:
            user = preference.user
            if not user.email:
                continue

            cursor = getattr(preference, cursor_field)
            notifications = list(Notification.objects.filter(
                recipient=user,
                read=False,
                pk__gt=cursor,
            ).order_by('pk')[:25])
            if not notifications:
                continue

            lines = [
                f'Hi {user.get_full_name() or user.username},',
                '',
                f'You have {len(notifications)} unread notification(s) from Teople:',
                '',
            ]
            lines.extend(f'- {item.title}: {item.message}' for item in notifications)
            lines.extend([
                '',
                f'Open Teople: {getattr(settings, "FRONTEND_URL", "")}',
            ])

            try:
                delivered = send_mail(
                    subject=f'Teople {frequency.title()} Notification Digest',
                    message='\n'.join(lines),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                if delivered != 1:
                    raise RuntimeError(f'Email backend reported {delivered} delivered messages.')
            except Exception:
                failed_count += 1
                logger.exception(
                    'Failed to send %s notification digest to user id %s.',
                    frequency,
                    user.pk,
                )
                continue

            setattr(preference, sent_at_field, timezone.now())
            setattr(preference, cursor_field, notifications[-1].pk)
            preference.save(update_fields=[sent_at_field, cursor_field, 'updated_at'])
            sent_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Sent {sent_count} {frequency} digest email(s); {failed_count} failed.'
        ))
