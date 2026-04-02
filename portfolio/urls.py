from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('add-fund/', views.add_fund, name='add_fund'),
    path('fund/<int:pf_id>/', views.fund_detail, name='fund_detail'),
    path('fund/<int:pf_id>/add-lot/', views.add_lot, name='add_lot'),
    path('fund/<int:pf_id>/remove/', views.remove_fund, name='remove_fund'),
    path('fund/<int:pf_id>/refresh-nav/', views.refresh_nav, name='refresh_nav'),
    path('lot/<int:lot_id>/delete/', views.delete_lot, name='delete_lot'),
    path('recalculate-xirr/', views.recalculate_xirr, name='recalculate_xirr'),
    path('settings/', views.settings_view, name='settings'),
    path('api/search/', views.api_fund_search, name='api_fund_search'),
]
