from django.db import models
from django.contrib.auth.models import User
from funds.models import MutualFund


class Alert(models.Model):
    ALERT_TYPES = [
        ('fund_manager_change', 'Fund Manager Change'),
        ('category_change', 'Fund Category Change'),
        ('objective_change', 'Fund Objective Change'),
        ('nav_update', 'NAV Update'),
        ('new_holding', 'New Holding Added'),
        ('holding_exit', 'Holding Fully Exited'),
        ('weight_change', 'Significant Weight Change'),
        ('sector_change', 'Sector Allocation Change'),
        ('system', 'System Alert'),
        ('factsheet_error', 'Factsheet Error'),
    ]

    SEVERITY = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alerts')
    fund = models.ForeignKey(MutualFund, on_delete=models.SET_NULL, null=True, blank=True)
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY, default='info')
    title = models.CharField(max_length=300)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    is_emailed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'is_read'])]

    def __str__(self):
        return f"[{self.alert_type}] {self.title}"

    def mark_read(self):
        self.is_read = True
        self.save(update_fields=['is_read'])
