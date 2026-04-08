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
def run_migrations(request):
    """Run Django migrations - SECURE VERSION"""
    # Only allow POST
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
        execute_from_command_line(['manage.py', 'migrate', '--fake-initial', '--noinput'])
        return JsonResponse({'status': 'success', 'message': 'Migrations completed successfully'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
