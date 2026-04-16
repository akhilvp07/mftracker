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
    """Create admin user - Vercel serverless function handler"""
    try:
        from django.contrib.auth.models import User
        
        # Get admin credentials from request or use defaults
        data = request.POST if request.POST else {}
        username = data.get('username', os.environ.get('ADMIN_USERNAME', 'admin'))
        email = data.get('email', os.environ.get('ADMIN_EMAIL', 'admin@example.com'))
        password = data.get('password', os.environ.get('ADMIN_PASSWORD', 'admin123'))
        
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
            return JsonResponse({
                'status': 'success',
                'message': f'Admin user "{username}" created successfully!',
                'username': username,
                'password': password,
                'warning': 'Please change the password after first login!'
            })
        else:
            # Update existing user
            user.is_staff = True
            user.is_superuser = True
            if password and password != 'admin123':  # Only update if not default
                user.set_password(password)
            user.save()
            return JsonResponse({
                'status': 'success',
                'message': f'Admin user "{username}" updated successfully!'
            })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# Also support the WSGI application
app = get_wsgi_application()
