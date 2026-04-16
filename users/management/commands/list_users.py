from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone


class Command(BaseCommand):
    help = 'List all users in the database'

    def add_arguments(self, parser):
        parser.add_argument('--active', action='store_true', help='Show only active users')
        parser.add_argument('--staff', action='store_true', help='Show only staff users')
        parser.add_argument('--count', action='store_true', help='Show only user count')

    def handle(self, *args, **options):
        queryset = User.objects.all()

        if options['active']:
            queryset = queryset.filter(is_active=True)
        
        if options['staff']:
            queryset = queryset.filter(is_staff=True)

        if options['count']:
            count = queryset.count()
            self.stdout.write(f"Total users: {count}")
            return

        self.stdout.write(self.style.SUCCESS('User List:'))
        self.stdout.write('-' * 80)
        self.stdout.write(f"{'Username':<20} {'Email':<30} {'Staff':<8} {'Active':<8} {'Last Login':<20}")
        self.stdout.write('-' * 80)

        for user in queryset:
            last_login = user.last_login.strftime('%Y-%m-%d %H:%M') if user.last_login else 'Never'
            self.stdout.write(
                f"{user.username:<20} {user.email or 'N/A':<30} "
                f"{'Yes' if user.is_staff else 'No':<8} "
                f"{'Yes' if user.is_active else 'No':<8} "
                f"{last_login:<20}"
            )

        self.stdout.write('-' * 80)
        self.stdout.write(f"Total: {queryset.count()} users")
