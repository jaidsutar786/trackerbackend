import os
from django.core.management.base import BaseCommand
from accounts.models import User

USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
PASSWORD = os.getenv('ADMIN_PASSWORD', 'Admin@1234')
EMAIL = os.getenv('ADMIN_EMAIL', 'admin@teople.com')


class Command(BaseCommand):
    help = 'Create or reset the default admin user'

    def handle(self, *args, **kwargs):
        user, created = User.objects.get_or_create(
            username=USERNAME,
            defaults={'email': EMAIL, 'role': 'admin', 'is_staff': True, 'is_superuser': True}
        )

        if created:
            user.set_password(PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f'Admin created!\n  Username: {USERNAME}\n  Password: {PASSWORD}'
            ))
        else:
            total = User.objects.filter(role='admin').count()
            self.stdout.write(self.style.WARNING(
                f'Admin already exists (total admins in DB: {total})\n'
                f'  Username : {user.username}\n'
                f'  Email    : {user.email}\n'
                f'  Active   : {user.is_active}\n'
                f'\nTo reset password run:\n'
                f'  python manage.py create_admin --reset'
            ))

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Reset admin password to default')

    def execute(self, *args, **options):
        if options.get('reset'):
            try:
                user = User.objects.get(username=USERNAME)
                user.set_password(PASSWORD)
                user.is_active = True
                user.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Password reset!\n  Username: {USERNAME}\n  Password: {PASSWORD}'
                ))
                return
            except User.DoesNotExist:
                pass
        super().execute(*args, **options)
