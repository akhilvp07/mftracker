from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.contrib.auth.forms import UserCreationForm
from django.views.generic import CreateView
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

class SignUpView(CreateView):
    form_class = UserCreationForm
    template_name = 'base/signup.html'
    success_url = '/accounts/login/'

@require_http_methods(["GET"])
def health_check(request):
    """Lightweight health check endpoint with no database queries."""
    return JsonResponse({"status": "ok"}, status=200)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='base/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/signup/', SignUpView.as_view(), name='signup'),
    path('health/', health_check, name='health_check'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('api.urls')),
    path('', lambda r: redirect('dashboard'), name='home'),
    path('dashboard/', include('portfolio.urls')),
    path('funds/', include('funds.urls')),
    path('alerts/', include('alerts.urls')),
    path('factsheets/', include('factsheets.urls')),
]
