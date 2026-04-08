from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.contrib.auth.models import User

@require_GET
def list_users_api(request):
    """API endpoint to list all users"""
    users = User.objects.all().values('username', 'email', 'date_joined', 'is_staff', 'is_superuser')
    return JsonResponse(list(users), safe=False)
