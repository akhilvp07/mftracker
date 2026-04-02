from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

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
