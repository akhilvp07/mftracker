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
        ('risk_alert', 'Risk Metric Alert'),
        ('aum_change', 'AUM Change'),
        ('expense_ratio_change', 'Expense Ratio Change'),
        ('rating_change', 'Rating Change'),
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


class AlertPreference(models.Model):
    """User preferences for different types of alerts"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alert_preferences')
    
    # Email notifications
    email_nav_changes = models.BooleanField(default=True, help_text="NAV movements > 5%")
    email_holdings_changes = models.BooleanField(default=True, help_text="New/exited holdings")
    email_sector_changes = models.BooleanField(default=False, help_text="Sector allocation changes")
    email_risk_alerts = models.BooleanField(default=True, help_text="Risk metric warnings")
    email_metadata_changes = models.BooleanField(default=False, help_text="Expense ratio, AUM, rating changes")
    
    # In-app notifications
    app_nav_changes = models.BooleanField(default=True)
    app_holdings_changes = models.BooleanField(default=True)
    app_sector_changes = models.BooleanField(default=True)
    app_risk_alerts = models.BooleanField(default=True)
    app_metadata_changes = models.BooleanField(default=True)
    
    # Thresholds
    nav_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=5.0, help_text="Percentage")
    weight_change_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=2.0, help_text="Percentage")
    sector_change_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=5.0, help_text="Percentage")
    
    # Daily digest
    daily_digest_enabled = models.BooleanField(default=False)
    digest_time = models.TimeField(default="09:00", help_text="Time for daily digest email")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Alert Preference"
        verbose_name_plural = "Alert Preferences"
    
    def __str__(self):
        return f"{self.user.username}'s Alert Preferences"
