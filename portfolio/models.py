from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator
from funds.models import MutualFund
import decimal
from django.core.exceptions import ValidationError
from django.utils import timezone


def format_indian_currency(amount):
    """Format number in Indian currency format"""
    try:
        s = str(int(round(float(amount))))
        
        if len(s) <= 3:
            return s
        elif len(s) <= 5:
            return f"{s[:-3]},{s[-3:]}"
        else:
            first_part = s[:-3]
            first_parts = []
            while first_part:
                first_parts.append(first_part[-2:])
                first_part = first_part[:-2]
            first_parts.reverse()
            return f"{','.join(first_parts)},{s[-3:]}"
    except (ValueError, TypeError):
        return str(amount)


class Portfolio(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='portfolio')
    name = models.CharField(max_length=200, default='My Portfolio')
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
    def total_cost_basis(self):
        """Traditional cost basis using FIFO method"""
        try:
            # Get all lots sorted by purchase_date (FIFO)
            lots = sorted(self.lots.all(), key=lambda x: x.purchase_date)
            purchase_queue = []  # Queue of (units, avg_nav, purchase_date)
            total_cost = decimal.Decimal('0')
            
            for lot in lots:
                if lot.units > 0:
                    # Purchase - add to queue
                    purchase_queue.append({
                        'units': lot.units,
                        'avg_nav': lot.avg_nav,
                        'purchase_date': lot.purchase_date
                    })
                else:
                    # Redemption - remove from FIFO queue
                    units_to_remove = abs(lot.units)
                    while units_to_remove > 0 and purchase_queue:
                        if purchase_queue[0]['units'] <= units_to_remove:
                            # Remove entire lot
                            units_to_remove -= purchase_queue[0]['units']
                            purchase_queue.pop(0)
                        else:
                            # Partially remove from lot
                            purchase_queue[0]['units'] -= units_to_remove
                            units_to_remove = 0
            
            # Calculate cost of remaining units
            for lot in purchase_queue:
                total_cost += lot['units'] * lot['avg_nav']
            
            # Ensure we return a valid Decimal
            return total_cost if total_cost else decimal.Decimal('0')
        except Exception as e:
            # Fallback to simple sum if FIFO fails
            return sum(lot.units * lot.avg_nav for lot in self.lots.all() if lot.units > 0) or decimal.Decimal('0')

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
    SOURCE_CHOICES = [
        ('MANUAL', 'Manual Entry'),
        ('CAS', 'CAS Parser'),
    ]
    
    TRANSACTION_TYPE_CHOICES = [
        ('PURCHASE', 'Purchase'),
        ('REDEMPTION', 'Redemption'),
        ('SWITCH_IN', 'Switch In'),
        ('SWITCH_OUT', 'Switch Out'),
        ('DIVIDEND_REINVEST', 'Dividend Reinvest'),
        ('HOLDING', 'Current Holding'),
    ]
    
    portfolio_fund = models.ForeignKey(PortfolioFund, on_delete=models.CASCADE, related_name='lots')
    units = models.DecimalField(max_digits=16, decimal_places=4)
    avg_nav = models.DecimalField(max_digits=14, decimal_places=4)
    purchase_date = models.DateField()
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # CAS Parser integration fields
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='MANUAL')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES, default='PURCHASE')
    cas_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    folio_number = models.CharField(max_length=50, blank=True, null=True)
    original_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_open = models.BooleanField(default=True)

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


class AssetAllocation(models.Model):
    """User's target asset allocation settings"""
    portfolio = models.OneToOneField(Portfolio, on_delete=models.CASCADE, related_name='asset_allocation')
    
    # Asset class allocation percentages (should sum to 100)
    equity_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=75,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    debt_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=15,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    gold_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Equity cap allocation percentages (should sum to 100)
    large_cap_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=60,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    mid_cap_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    small_cap_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Rebalancing settings
    rebalance_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        help_text="Trigger rebalancing when allocation deviates by this percentage",
        validators=[MinValueValidator(0), MaxValueValidator(50)]
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Asset Allocation"
        verbose_name_plural = "Asset Allocations"
    
    def __str__(self):
        return f"{self.portfolio.user.username}'s Asset Allocation"
    
    def clean(self):
        # Validate that percentages sum to 100
        asset_total = self.equity_percentage + self.debt_percentage + self.gold_percentage
        if asset_total != 100:
            raise ValidationError(f"Asset allocation must sum to 100%, currently {asset_total}%")
        
        cap_total = self.large_cap_percentage + self.mid_cap_percentage + self.small_cap_percentage
        if cap_total != 100:
            raise ValidationError(f"Equity cap allocation must sum to 100%, currently {cap_total}%")


class RebalanceSuggestion(models.Model):
    """Generated rebalancing suggestions for a portfolio"""
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='rebalance_suggestions')
    date = models.DateTimeField(auto_now_add=True)
    
    # Current allocation
    current_equity = models.DecimalField(max_digits=5, decimal_places=2)
    current_debt = models.DecimalField(max_digits=5, decimal_places=2)
    current_gold = models.DecimalField(max_digits=5, decimal_places=2)
    
    # Target allocation
    target_equity = models.DecimalField(max_digits=5, decimal_places=2)
    target_debt = models.DecimalField(max_digits=5, decimal_places=2)
    target_gold = models.DecimalField(max_digits=5, decimal_places=2)
    
    # Total portfolio value for calculation
    total_value = models.DecimalField(max_digits=14, decimal_places=2)
    
    is_applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-date']
    
    def __str__(self):
        return f"Rebalance suggestion for {self.portfolio.user.username} - {self.date.strftime('%Y-%m-%d')}"


class RebalanceAction(models.Model):
    """Individual buy/sell actions in a rebalancing suggestion"""
    suggestion = models.ForeignKey(RebalanceSuggestion, on_delete=models.CASCADE, related_name='actions')
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, null=True, blank=True)
    
    ACTION_CHOICES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]
    action = models.CharField(max_length=4, choices=ACTION_CHOICES)
    
    # Amount in currency (not units)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    
    # Calculated units based on current NAV
    units = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    
    # Reason for this action
    reason = models.CharField(max_length=200)
    
    class Meta:
        ordering = ['action', '-amount']
    
    def __str__(self):
        if self.action == 'BUY':
            return f"{self.action} ₹{format_indian_currency(self.amount)} of {self.fund.scheme_name}"
        else:
            return f"{self.action} ₹{format_indian_currency(self.amount)} of {self.fund.scheme_name}"


class CASImport(models.Model):
    """Track CAS import sessions and their status"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partial Success'),
        ('DUPLICATE', 'Duplicate'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cas_imports')
    filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    file_hash = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    skipped_transactions = models.PositiveIntegerField(default=0)
    
    # CAS Parser response data
    investor_name = models.CharField(max_length=200, blank=True, null=True)
    investor_pan = models.CharField(max_length=10, blank=True, null=True)
    cas_type = models.CharField(max_length=20, blank=True, null=True)
    statement_period_from = models.DateField(null=True, blank=True, db_index=True)
    statement_period_to = models.DateField(null=True, blank=True, db_index=True)
    
    # Processing results
    total_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    funds_processed = models.IntegerField(default=0)
    transactions_processed = models.IntegerField(default=0)
    errors_count = models.IntegerField(default=0)
    
    # Error handling
    error_message = models.TextField(blank=True, null=True)
    parser_response = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"CAS Import - {self.user.username} - {self.filename} ({self.status})"
    
    @property
    def duration(self):
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    def mark_started(self):
        self.status = 'PROCESSING'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_completed(self, success=True, error_message=None):
        self.status = 'COMPLETED' if success else 'FAILED'
        self.completed_at = timezone.now()
        if error_message:
            self.error_message = error_message
        self.save(update_fields=['status', 'completed_at', 'error_message'])


class CASTransaction(models.Model):
    """Detailed transaction records from CAS imports"""
    TRANSACTION_TYPE_CHOICES = [
        ('PURCHASE', 'Purchase'),
        ('REDEMPTION', 'Redemption'),
        ('SWITCH_IN', 'Switch In'),
        ('SWITCH_OUT', 'Switch Out'),
        ('DIVIDEND_PAYOUT', 'Dividend Payout'),
        ('DIVIDEND_REINVEST', 'Dividend Reinvest'),
    ]
    
    cas_import = models.ForeignKey(CASImport, on_delete=models.CASCADE, related_name='transactions')
    portfolio_fund = models.ForeignKey(PortfolioFund, on_delete=models.CASCADE, related_name='cas_transactions', null=True, blank=True)
    fund = models.ForeignKey(MutualFund, on_delete=models.CASCADE, related_name='cas_transactions')
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    transaction_date = models.DateField()
    units = models.DecimalField(max_digits=16, decimal_places=4)
    nav = models.DecimalField(max_digits=14, decimal_places=4)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    
    # Additional details
    folio_number = models.CharField(max_length=50, blank=True, null=True)
    balance_units = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    
    # Original CAS data
    raw_data = models.JSONField(default=dict, blank=True)
    
    # Processing status
    is_processed = models.BooleanField(default=False)
    purchase_lot = models.ForeignKey(PurchaseLot, on_delete=models.SET_NULL, null=True, blank=True, related_name='cas_transaction')
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['transaction_date']
        indexes = [
            models.Index(fields=['cas_import', 'transaction_date']),
            models.Index(fields=['fund', 'transaction_date']),
            models.Index(fields=['transaction_type']),
        ]
        unique_together = ['cas_import', 'fund', 'transaction_date', 'transaction_type', 'units', 'nav']
    
    def __str__(self):
        return f"{self.fund.scheme_name} - {self.transaction_type} - {self.transaction_date}: {self.units} @ {self.nav}"


