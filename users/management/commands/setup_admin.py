from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os


class Command(BaseCommand):
    help = 'Create or update admin user'

    def handle(self, *args, **options):
        # Get admin credentials from environment or use defaults
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
        password = os.environ.get('ADMIN_PASSWORD', 'admin123')

        # Check if user exists
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_staff': True,
                'is_superuser': True,
            }
        )

        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f'Admin user "{username}" created successfully!')
            )
            self.stdout.write(f'Username: {username}')
            self.stdout.write(f'Password: {password}')
            self.stdout.write(self.style.WARNING('Please change the password after first login!'))
        else:
            # Update existing user
            user.is_staff = True
            user.is_superuser = True
            if password:
                user.set_password(password)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f'Admin user "{username}" updated successfully!')
            )

        # Show admin URL
        self.stdout.write(f'\nAdmin URL: http://localhost:8000/admin/')
        self.stdout.write(f'Production Admin URL: https://mftracker-zeta.vercel.app/admin/')
