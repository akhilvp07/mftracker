from django.contrib import admin
from .models import Portfolio, PortfolioFund, PurchaseLot, XIRRCache

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'created_at']

@admin.register(PortfolioFund)
class PortfolioFundAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'fund', 'total_units', 'total_invested', 'created_at']
    search_fields = ['fund__scheme_name', 'portfolio__user__username']

@admin.register(PurchaseLot)
class PurchaseLotAdmin(admin.ModelAdmin):
    list_display = ['portfolio_fund', 'units', 'avg_nav', 'purchase_date']
    date_hierarchy = 'purchase_date'

@admin.register(XIRRCache)
class XIRRCacheAdmin(admin.ModelAdmin):
    list_display = ['portfolio_fund', 'portfolio', 'xirr_value', 'calculated_at']
