import os
import sys
from django.core.management import call_command
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.wsgi import get_wsgi_application

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Setup Django
import django
django.setup()

@csrf_exempt
@require_POST
def handler(request):
    """Run Django migrations - Vercel serverless function handler"""
    try:
        # Run migrations
        call_command('migrate', '--noinput')
        
        return JsonResponse({
            'status': 'success',
            'message': 'Migrations applied successfully'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# Also support the WSGI application
app = get_wsgi_application()
