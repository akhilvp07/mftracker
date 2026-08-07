from django.urls import path
from . import migrate
from . import views

urlpatterns = [
    path('migrate', migrate.handler, name='migrate'),
    path('dashboard/', views.dashboard_api, name='api_dashboard'),
    path('funds/', views.funds_list, name='api_funds_list'),
    path('funds/<str:scheme_code>/', views.fund_detail, name='api_fund_detail'),
    path('refresh-nav/', views.refresh_nav_api, name='api_refresh_nav'),
    path('recalc-xirr/', views.recalc_xirr_api, name='api_recalc_xirr'),
]
