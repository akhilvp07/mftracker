from django.contrib import admin
from .models import Portfolio, PortfolioFund, PurchaseLot, XIRRCache, CASImport, CASTransaction

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'created_at']

@admin.register(PortfolioFund)
class PortfolioFundAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'fund', 'total_units', 'total_invested', 'created_at']
    search_fields = ['fund__scheme_name', 'portfolio__user__username']

@admin.register(PurchaseLot)
class PurchaseLotAdmin(admin.ModelAdmin):
    list_display = ['portfolio_fund', 'units', 'avg_nav', 'purchase_date', 'source', 'transaction_type']
    list_filter = ['source', 'transaction_type', 'purchase_date']
    date_hierarchy = 'purchase_date'
    search_fields = ['portfolio_fund__fund__scheme_name', 'folio_number']
    readonly_fields = ['cas_transaction_id']

@admin.register(XIRRCache)
class XIRRCacheAdmin(admin.ModelAdmin):
    list_display = ['portfolio_fund', 'portfolio', 'xirr_value', 'calculated_at', 'error_message']
    list_filter = ['calculated_at']

@admin.register(CASImport)
class CASImportAdmin(admin.ModelAdmin):
    list_display = ['user', 'filename', 'status', 'funds_processed', 'transactions_processed', 'created_at']
    list_filter = ['status', 'created_at', 'cas_type']
    search_fields = ['user__username', 'filename', 'investor_name']
    readonly_fields = ['parser_response', 'created_at', 'started_at', 'completed_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'filename', 'file_size', 'status')
        }),
        ('CAS Data', {
            'fields': ('investor_name', 'investor_pan', 'cas_type', 'statement_period_from', 'statement_period_to')
        }),
        ('Processing Results', {
            'fields': ('total_value', 'funds_processed', 'transactions_processed', 'errors_count')
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Technical Details', {
            'fields': ('parser_response', 'created_at', 'started_at', 'completed_at'),
            'classes': ('collapse',)
        })
    )

@admin.register(CASTransaction)
class CASTransactionAdmin(admin.ModelAdmin):
    list_display = ['fund', 'transaction_type', 'transaction_date', 'units', 'nav', 'amount', 'is_processed']
    list_filter = ['transaction_type', 'transaction_date', 'is_processed']
    search_fields = ['fund__scheme_name', 'folio_number']
    date_hierarchy = 'transaction_date'
    readonly_fields = ['cas_import', 'raw_data']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('cas_import', 'portfolio_fund', 'fund', 'transaction_type', 'transaction_date')
        }),
        ('Financial Details', {
            'fields': ('units', 'nav', 'amount', 'folio_number', 'balance_units')
        }),
        ('Processing', {
            'fields': ('is_processed', 'purchase_lot')
        }),
        ('Technical Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        })
    )

