from django.urls import path
from django.http import JsonResponse
from . import views

urlpatterns = [
    path('seed/', views.seed_view, name='seed_funds'),
]
