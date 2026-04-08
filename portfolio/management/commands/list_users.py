from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'List all users in the database'

    def handle(self, *args, **options):
        users = User.objects.all()
        
        if not users:
            self.stdout.write(self.style.WARNING('No users found in the database.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Total users: {users.count()}'))
        self.stdout.write('\nRegistered users:')
        self.stdout.write('-' * 50)
        
        for user in users:
            is_staff = 'Staff' if user.is_staff else ''
            is_superuser = 'Superuser' if user.is_superuser else ''
            status = f' [{is_staff}{is_superuser}]' if is_staff or is_superuser else ''
            
            self.stdout.write(
                f'• {user.username}{status}'
                f'  Email: {user.email}'
                f'  Joined: {user.date_joined.strftime("%Y-%m-%d %H:%M")}'
            )
