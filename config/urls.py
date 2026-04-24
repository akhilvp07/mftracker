from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.contrib.auth.forms import UserCreationForm
from django.views.generic import CreateView

class SignUpView(CreateView):
    form_class = UserCreationForm
    template_name = 'base/signup.html'
    success_url = '/accounts/login/'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='base/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/signup/', SignUpView.as_view(), name='signup'),
    path('', lambda r: redirect('dashboard'), name='home'),
    path('dashboard/', include('portfolio.urls')),
    path('funds/', include('funds.urls')),
    path('alerts/', include('alerts.urls')),
    path('factsheets/', include('factsheets.urls')),
    path('api/migrate', include('api.urls')),
]
