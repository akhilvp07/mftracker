from django.urls import path
from . import views

urlpatterns = [
    path('<int:fund_id>/', views.factsheet_view, name='factsheet'),
    path('<int:fund_id>/refresh/', views.refresh_factsheet, name='refresh_factsheet'),
]
