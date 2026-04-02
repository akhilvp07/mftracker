from django.db import models
from funds.models import MutualFund
import json


class Factsheet(models.Model):
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, related_name='factsheets')
    month = models.DateField()  # First day of the month
    fund_manager = models.CharField(max_length=300, blank=True)
    category = models.CharField(max_length=200, blank=True)
    objective = models.TextField(blank=True)
    aum = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    expense_ratio = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    fetch_error = models.TextField(blank=True)

    class Meta:
        unique_together = ('fund', 'month')
        ordering = ['-month']

    def __str__(self):
        return f"{self.fund.scheme_name} - {self.month.strftime('%b %Y')}"


class FactsheetHolding(models.Model):
    factsheet = models.ForeignKey(Factsheet, on_delete=models.CASCADE, related_name='holdings')
    stock_name = models.CharField(max_length=300)
    isin = models.CharField(max_length=20, blank=True)
    weight = models.DecimalField(max_digits=6, decimal_places=4)  # Percentage
    sector = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-weight']

    def __str__(self):
        return f"{self.stock_name}: {self.weight}%"


class SectorAllocation(models.Model):
    factsheet = models.ForeignKey(Factsheet, on_delete=models.CASCADE, related_name='sectors')
    sector_name = models.CharField(max_length=200)
    weight = models.DecimalField(max_digits=6, decimal_places=4)

    class Meta:
        ordering = ['-weight']

    def __str__(self):
        return f"{self.sector_name}: {self.weight}%"


class FactsheetDiff(models.Model):
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, related_name='diffs')
    current_month = models.ForeignKey(Factsheet, on_delete=models.CASCADE, related_name='diffs_as_current')
    previous_month = models.ForeignKey(Factsheet, on_delete=models.CASCADE, related_name='diffs_as_previous', null=True, blank=True)
    new_holdings = models.JSONField(default=list)
    exited_holdings = models.JSONField(default=list)
    weight_changes = models.JSONField(default=list)
    sector_changes = models.JSONField(default=list)
    manager_changed = models.BooleanField(default=False)
    category_changed = models.BooleanField(default=False)
    objective_changed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('fund', 'current_month')

    def __str__(self):
        return f"{self.fund.scheme_name} diff - {self.current_month.month.strftime('%b %Y')}"


class FactsheetFetchLog(models.Model):
    fund = models.ForeignKey(MutualFund, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='running')
    funds_processed = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Fetch {self.started_at} - {self.status}"
