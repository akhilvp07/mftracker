from django.db import models
from django.utils import timezone


class MutualFund(models.Model):
    scheme_code = models.IntegerField(unique=True, db_index=True)
    scheme_name = models.CharField(max_length=500)
    amc = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=200, blank=True)
    fund_type = models.CharField(max_length=100, blank=True)
    current_nav = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    nav_date = models.DateField(null=True, blank=True)
    nav_last_updated = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheme_name']
        indexes = [
            models.Index(fields=['scheme_name']),
            models.Index(fields=['amc']),
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
