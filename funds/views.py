from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.management import execute_from_command_line

@login_required
@require_POST
def seed_view(request):
    from .services import seed_fund_database
    try:
        seed_fund_database(force=True)
        messages.success(request, 'Fund database seeded successfully.')
    except Exception as e:
        messages.error(request, f'Seeding failed: {e}')
    return redirect('settings')

@csrf_exempt
def create_superuser(request):
    """Create a superuser - for initial setup"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    # Check for secret key
    from django.conf import settings
    import hmac
    
    secret = request.headers.get('X-Migration-Secret')
    expected_secret = getattr(settings, 'MIGRATION_SECRET', None)
    
    if not expected_secret or not hmac.compare_digest(secret, expected_secret):
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        # Get or create superuser
        from django.contrib.auth.models import User
        username = request.POST.get('username', 'admin')
        email = request.POST.get('email', 'admin@example.com')
        password = request.POST.get('password', 'admin123')
        
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            return JsonResponse({'status': 'success', 'message': f'Superuser {username} created'})
        else:
            return JsonResponse({'status': 'info', 'message': f'User {username} already exists'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def debug_static(request):
    """Debug static files configuration"""
    from django.templatetags.static import static
    return JsonResponse({
        'STATIC_URL': settings.STATIC_URL,
        'STATIC_ROOT': settings.STATIC_ROOT,
        'STATICFILES_DIRS': settings.STATICFILES_DIRS,
        'css_url': static('css/main.css'),
        'js_url': static('js/main.js')
    })
