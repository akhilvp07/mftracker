from django.urls import path
from . import views

urlpatterns = [
    path('', views.alert_list, name='alerts'),
    path('settings/', views.alert_settings, name='alert_settings'),
    path('<int:alert_id>/read/', views.mark_read, name='mark_alert_read'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_alerts_read'),
    path('delete/<int:alert_id>/', views.delete_alert, name='delete_alert'),
]
