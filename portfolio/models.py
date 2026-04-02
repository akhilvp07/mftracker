from django.db import models
from django.contrib.auth.models import User
from funds.models import MutualFund
import decimal


class Portfolio(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='portfolio')
    name = models.CharField(max_length=200, default='My Portfolio')
    kite_access_token = models.CharField(max_length=500, blank=True)
    kite_connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Portfolio"

    def get_or_create_for_user(user):
        portfolio, _ = Portfolio.objects.get_or_create(user=user)
        return portfolio


class PortfolioFund(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='holdings')
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, related_name='portfolio_entries')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('portfolio', 'fund')

    def __str__(self):
        return f"{self.portfolio.user.username} - {self.fund.scheme_name}"

    @property
    def total_units(self):
        return sum(lot.units for lot in self.lots.all())

    @property
    def total_invested(self):
        return sum(lot.units * lot.avg_nav for lot in self.lots.all())

    @property
    def current_value(self):
        nav = self.fund.current_nav
        if nav:
            return self.total_units * nav
        return decimal.Decimal('0')

    @property
    def absolute_gain(self):
        return self.current_value - self.total_invested

    @property
    def gain_pct(self):
        if self.total_invested > 0:
            return (self.absolute_gain / self.total_invested) * 100
        return decimal.Decimal('0')


class PurchaseLot(models.Model):
    portfolio_fund = models.ForeignKey(PortfolioFund, on_delete=models.CASCADE, related_name='lots')
    units = models.DecimalField(max_digits=16, decimal_places=4)
    avg_nav = models.DecimalField(max_digits=14, decimal_places=4)
    purchase_date = models.DateField()
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['purchase_date']

    def __str__(self):
        return f"{self.portfolio_fund.fund.scheme_name} - {self.purchase_date}: {self.units} units @ {self.avg_nav}"

    @property
    def invested_amount(self):
        return self.units * self.avg_nav


class XIRRCache(models.Model):
    portfolio_fund = models.ForeignKey(PortfolioFund, on_delete=models.CASCADE, related_name='xirr_cache', null=True, blank=True)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='xirr_cache', null=True, blank=True)
    xirr_value = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)
    error_message = models.CharField(max_length=300, blank=True)

    class Meta:
        indexes = [models.Index(fields=['portfolio_fund']), models.Index(fields=['portfolio'])]
