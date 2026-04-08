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
    from django.conf import settings
    from django.templatetags.static import static
    import os
    
    # Check both STATIC_ROOT and source directory
    css_path_root = os.path.join(settings.STATIC_ROOT, 'css/main.css')
    js_path_root = os.path.join(settings.STATIC_ROOT, 'js/main.js')
    
    # Check source directory
    source_static = settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else None
    css_path_source = os.path.join(source_static, 'css/main.css') if source_static else None
    js_path_source = os.path.join(source_static, 'js/main.js') if source_static else None
    
    # List directories
    staticfiles_list = []
    if os.path.exists(settings.STATIC_ROOT):
        for root, dirs, files in os.walk(settings.STATIC_ROOT):
            for file in files[:10]:
                rel_path = os.path.relpath(os.path.join(root, file), settings.STATIC_ROOT)
                staticfiles_list.append(f"STATIC_ROOT/{rel_path}")
    
    source_list = []
    if source_static and os.path.exists(source_static):
        for root, dirs, files in os.walk(source_static):
            for file in files[:10]:
                rel_path = os.path.relpath(os.path.join(root, file), source_static)
                source_list.append(f"source/{rel_path}")
    
    return JsonResponse({
        'STATIC_URL': settings.STATIC_URL,
        'STATIC_ROOT': str(settings.STATIC_ROOT),
        'STATICFILES_DIRS': [str(path) for path in settings.STATICFILES_DIRS],
        'css_url': static('css/main.css'),
        'js_url': static('js/main.js'),
        'css_exists_root': os.path.exists(css_path_root),
        'js_exists_root': os.path.exists(js_path_root),
        'css_exists_source': os.path.exists(css_path_source) if css_path_source else False,
        'js_exists_source': os.path.exists(js_path_source) if js_path_source else False,
        'css_path_root': css_path_root,
        'js_path_root': js_path_root,
        'css_path_source': css_path_source,
        'js_path_source': js_path_source,
        'staticfiles_root_exists': os.path.exists(settings.STATIC_ROOT),
        'source_static_exists': os.path.exists(source_static) if source_static else False,
        'staticfiles_list': staticfiles_list,
        'source_list': source_list
    })
