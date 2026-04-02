from django.contrib import admin
from .models import Factsheet, FactsheetHolding, SectorAllocation, FactsheetDiff, FactsheetFetchLog

@admin.register(Factsheet)
class FactsheetAdmin(admin.ModelAdmin):
    list_display = ['fund', 'month', 'fund_manager', 'category', 'fetched_at']
    search_fields = ['fund__scheme_name', 'fund_manager']
    date_hierarchy = 'month'

@admin.register(FactsheetDiff)
class FactsheetDiffAdmin(admin.ModelAdmin):
    list_display = ['fund', 'current_month', 'manager_changed', 'category_changed', 'created_at']
    list_filter = ['manager_changed', 'category_changed', 'objective_changed']

@admin.register(FactsheetFetchLog)
class FactsheetFetchLogAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'status', 'funds_processed', 'errors', 'finished_at']
    list_filter = ['status']
