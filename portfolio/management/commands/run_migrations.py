from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.http import JsonResponse
import json


class Command(BaseCommand):
    help = 'Run migrations and return JSON response for API usage'

    def handle(self, *args, **options):
        try:
            # Run migrations
            call_command('migrate', '--noinput')
            
            result = {
                'status': 'success',
                'message': 'Migrations applied successfully'
            }
            self.stdout.write(json.dumps(result))
            
        except Exception as e:
            result = {
                'status': 'error',
                'message': str(e)
            }
            self.stdout.write(json.dumps(result))
            raise
