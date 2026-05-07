from django.urls import path
from . import migrate

urlpatterns = [
    path('', migrate.handler, name='migrate'),
]
