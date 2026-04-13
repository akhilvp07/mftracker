"""
XIRR calculation using Newton-Raphson method via scipy.optimize.
"""
import logging
from datetime import date
from decimal import Decimal
from scipy.optimize import brentq
import numpy as np

logger = logging.getLogger(__name__)


def xirr(cashflows):
    """
    Calculate XIRR given a list of (date, amount) tuples.
    Negative amounts = outflows (purchases), positive = inflows (current value).
    Returns annualized rate as a float, or None on failure.
    """
    if not cashflows or len(cashflows) < 2:
        return None

    cashflows = sorted(cashflows, key=lambda x: x[0])
    dates = [cf[0] for cf in cashflows]
    amounts = [float(cf[1]) for cf in cashflows]

    if all(a <= 0 for a in amounts) or all(a >= 0 for a in amounts):
        return None

    base_date = dates[0]
    years = [(d - base_date).days / 365.0 for d in dates]

    def npv(rate):
        return sum(a / (1 + rate) ** t for a, t in zip(amounts, years))

    try:
        result = brentq(npv, -0.9999, 100.0, xtol=1e-6, maxiter=1000)
        return result
    except (ValueError, RuntimeError) as e:
        logger.warning(f"XIRR brentq failed: {e}")
        return None


def calculate_fund_xirr(portfolio_fund):
    """Calculate XIRR for a single portfolio fund entry."""
    from .models import XIRRCache, CASTransaction
    
    lots = portfolio_fund.lots.all()
    if not lots:
        return None

    cashflows = []
    
    # Add all lots as cashflows
    # Positive lots = purchases (outflows)
    # Negative lots = redemptions (inflows)
    for lot in lots:
        if lot.units > 0:  # Purchase - money going out
            cashflows.append((lot.purchase_date, -float(lot.units * lot.avg_nav)))
        elif lot.units < 0:  # Redemption - money coming in
            cashflows.append((lot.purchase_date, float(abs(lot.units) * lot.avg_nav)))
    
    # Add redemption transactions from CAS as inflows
    try:
        cas_redemptions = CASTransaction.objects.filter(
            portfolio_fund=portfolio_fund,
            transaction_type__in=['REDEMPTION', 'SWITCH_OUT']
        ).order_by('transaction_date')
        
        for redemption in cas_redemptions:
            cashflows.append((redemption.transaction_date, float(redemption.amount)))
            
    except Exception as e:
        logger.warning(f"Error including CAS redemptions in XIRR: {e}")

    current_nav = portfolio_fund.fund.current_nav
    if not current_nav:
        return None

    total_units = sum(lot.units for lot in lots)
    current_value = float(total_units * Decimal(str(current_nav)))
    today = date.today()
    cashflows.append((today, current_value))

    rate = xirr(cashflows)
    
    # Cache result
    XIRRCache.objects.update_or_create(
        portfolio_fund=portfolio_fund,
        defaults={
            'xirr_value': round(rate, 6) if rate is not None else None,
            'error_message': '' if rate is not None else 'Could not converge'
        }
    )
    return rate


def calculate_portfolio_xirr(portfolio):
    """Calculate XIRR for the entire portfolio."""
    from .models import XIRRCache, CASTransaction

    cashflows = []
    
    # Add all lots as cashflows
    # Positive lots = purchases (outflows)
    # Negative lots = redemptions (inflows)
    for pf in portfolio.holdings.select_related('fund').prefetch_related('lots'):
        for lot in pf.lots.all():
            if lot.units > 0:  # Purchase - money going out
                cashflows.append((lot.purchase_date, -float(lot.units * lot.avg_nav)))
            elif lot.units < 0:  # Redemption - money coming in
                cashflows.append((lot.purchase_date, float(abs(lot.units) * lot.avg_nav)))
    
    # Add single current value for entire portfolio
    total_current_value = Decimal('0')
    for pf in portfolio.holdings.select_related('fund').prefetch_related('lots'):
        current_nav = pf.fund.current_nav
        if current_nav:
            total_units = sum(lot.units for lot in pf.lots.all())
            total_current_value += total_units * Decimal(str(current_nav))
    
    cashflows.append((date.today(), float(total_current_value)))
    
    # Add redemption transactions from CAS as inflows
    try:
        cas_redemptions = CASTransaction.objects.filter(
            portfolio_fund__portfolio=portfolio,
            transaction_type__in=['REDEMPTION', 'SWITCH_OUT']
        ).order_by('transaction_date')
        
        for redemption in cas_redemptions:
            cashflows.append((redemption.transaction_date, float(redemption.amount)))
            
    except Exception as e:
        logger.warning(f"Error including CAS redemptions in portfolio XIRR: {e}")

    rate = xirr(cashflows) if cashflows else None

    XIRRCache.objects.update_or_create(
        portfolio=portfolio,
        portfolio_fund=None,
        defaults={
            'xirr_value': round(rate, 6) if rate is not None else None,
            'error_message': '' if rate is not None else 'Could not converge'
        }
    )
    return rate
