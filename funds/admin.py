from django.contrib import admin
from .models import MutualFund, NAVHistory, SeedStatus

@admin.register(MutualFund)
class MutualFundAdmin(admin.ModelAdmin):
    list_display = ['scheme_code', 'scheme_name', 'amc', 'current_nav', 'nav_date', 'is_active']
    search_fields = ['scheme_name', 'scheme_code', 'amc']
    list_filter = ['is_active', 'amc']
    readonly_fields = ['nav_last_updated', 'created_at', 'updated_at']

@admin.register(NAVHistory)
class NAVHistoryAdmin(admin.ModelAdmin):
    list_display = ['fund', 'date', 'nav']
    list_filter = ['fund']
    search_fields = ['fund__scheme_name']
    date_hierarchy = 'date'

@admin.register(SeedStatus)
class SeedStatusAdmin(admin.ModelAdmin):
    list_display = ['status', 'total_funds', 'last_seeded']
