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
    """Run Django migrations - for initial setup"""
    if request.method == 'POST':
        try:
            execute_from_command_line(['manage.py', 'migrate', '--noinput'])
            return JsonResponse({'status': 'success', 'message': 'Migrations completed successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'ready', 'message': 'POST to run migrations'})
