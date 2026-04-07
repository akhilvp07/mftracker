from django.db import models
from django.utils import timezone


class MutualFund(models.Model):
    # Basic identifiers
    scheme_code = models.IntegerField(unique=True, db_index=True)
    scheme_name = models.CharField(max_length=500)
    isin = models.CharField(max_length=20, blank=True, db_index=True, help_text="ISIN Div Payout/IDCW")
    
    # AMC and classification
    amc = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=200, blank=True)
    fund_type = models.CharField(max_length=100, blank=True)
    fund_category = models.CharField(max_length=200, blank=True, help_text="Detailed fund category from API")
    plan = models.CharField(max_length=50, blank=True, help_text="GROWTH/DIVIDEND etc")
    
    # Fund management details
    fund_manager = models.CharField(max_length=300, blank=True)
    investment_objective = models.TextField(blank=True)
    crisil_rating = models.CharField(max_length=50, blank=True)
    
    # Financial metrics
    current_nav = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    nav_date = models.DateField(null=True, blank=True)
    nav_last_updated = models.DateTimeField(null=True, blank=True)
    expense_ratio = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    aum = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, help_text="Assets Under Management in crores")
    face_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    
    # Dates and maturity
    start_date = models.DateField(null=True, blank=True, help_text="Scheme inception date")
    maturity_type = models.CharField(max_length=50, blank=True, help_text="Open Ended/Close Ended")
    
    # Investment and redemption flags
    direct = models.CharField(max_length=1, blank=True, help_text="Y/N for direct plan")
    redemption_allowed = models.CharField(max_length=1, blank=True, help_text="Y/N")
    lump_available = models.CharField(max_length=1, blank=True, help_text="Y/N")
    sip_available = models.CharField(max_length=1, blank=True, help_text="Y/N")
    
    # Additional metadata
    tags = models.JSONField(default=list, blank=True, help_text="Tags from API")
    
    # System fields
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheme_name']
        indexes = [
            models.Index(fields=['scheme_name']),
            models.Index(fields=['amc']),
            models.Index(fields=['isin']),
        ]

    def __str__(self):
        return f"{self.scheme_name} ({self.scheme_code})"


class NAVHistory(models.Model):
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, related_name='nav_history')
    date = models.DateField()
    nav = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        unique_together = ('fund', 'date')
        ordering = ['-date']
        indexes = [models.Index(fields=['fund', 'date'])]

    def __str__(self):
        return f"{self.fund.scheme_name} - {self.date}: {self.nav}"


class SeedStatus(models.Model):
    """Track database seeding status."""
    last_seeded = models.DateTimeField(null=True, blank=True)
    total_funds = models.IntegerField(default=0)
    status = models.CharField(max_length=50, default='pending')  # pending, running, done, failed
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Seed Status'

    def __str__(self):
        return f"Seed: {self.status} ({self.total_funds} funds)"
