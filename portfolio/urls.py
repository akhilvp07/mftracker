from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('add-fund/', views.add_fund, name='add_fund'),
    path('fund/<int:pf_id>/', views.fund_detail, name='fund_detail'),
    path('fund/<int:pf_id>/edit/', views.edit_fund, name='edit_fund'),
    path('add_lot/<int:pf_id>/', views.add_lot, name='add_lot'),
    path('fund/<int:pf_id>/remove/', views.remove_fund, name='remove_fund'),
    path('fund/<int:pf_id>/refresh-nav/', views.refresh_nav, name='refresh_nav'),
    path('refresh-all-nav/', views.refresh_all_nav, name='refresh_all_nav'),
    path('bulk-nav-refresh/', views.refresh_all_nav, name='bulk_nav_refresh'),
    # Debug endpoints
    path('debug/day-change/<str:scheme_code>/', views_debug.debug_fund_day_change, name='debug_fund_day_change'),
    path('lot/<int:lot_id>/delete/', views.delete_lot, name='delete_lot'),
    path('recalculate-xirr/', views.recalculate_xirr, name='recalculate_xirr'),
    path('settings/', views.settings_view, name='settings'),
    path('rebalance/', views.rebalance_view, name='rebalance'),
    path('api/search/', views.api_fund_search, name='api_fund_search'),
    path('api/rebalance-progress/', views.api_rebalance_progress, name='api_rebalance_progress'),
    path('api/cron/refresh-nav/', views.cron_refresh_nav, name='cron_refresh_nav'),
    path('api/run-migrations/', views.run_migrations_api, name='run_migrations_api'),
    path('api/setup-admin/', views.setup_admin_api, name='setup_admin_api'),
        
    # CAS Parser integration
    path('cas-import/', views.cas_unified, name='cas_import'),  # Redirect to unified view
    path('cas-import/upload/', views.cas_upload, name='cas_upload'),
    path('cas-import/<int:import_id>/', views.cas_import_detail, name='cas_import_detail'),
    path('api/cas-import-progress/', views.api_cas_import_progress, name='api_cas_import_progress'),
]
