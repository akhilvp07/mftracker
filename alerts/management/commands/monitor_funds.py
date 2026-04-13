from django.core.management.base import BaseCommand
from alerts.monitoring import run_monitoring


class Command(BaseCommand):
    help = 'Monitor funds for changes and create alerts'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Monitor funds for specific user only',
        )
    
    def handle(self, *args, **options):
        if options['user']:
            from django.contrib.auth.models import User
            from alerts.monitoring import FundMonitor
            
            try:
                user = User.objects.get(username=options['user'])
                monitor = FundMonitor()
                monitor.check_user_funds(user)
                self.stdout.write(f"Monitoring completed for user: {user.username}")
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User '{options['user']}' not found"))
        else:
            run_monitoring()
            self.stdout.write(self.style.SUCCESS('Fund monitoring completed for all users'))
