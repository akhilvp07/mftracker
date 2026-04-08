from django.urls import path
from django.http import JsonResponse
from . import views

urlpatterns = [
    path('seed/', views.seed_view, name='seed_funds'),
    path('create-superuser/', views.create_superuser, name='create_superuser'),
    path('debug-static/', views.debug_static, name='debug_static'),
]
