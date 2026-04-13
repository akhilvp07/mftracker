"""
Utility functions for portfolio management
"""
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)


def get_latest_business_day(current_date):
    """
    Get the latest business day considering weekends and holidays
    """
    from datetime import date
    
    # List of market holidays (can be extended)
    # Format: (day, month)
    MARKET_HOLIDAYS = [
        (1, 1),   # New Year's Day
        (26, 1),  # Republic Day
        (15, 8),  # Independence Day
        (2, 10),  # Gandhi Jayanti
        (25, 12), # Christmas
        # Add more holidays as needed
    ]
    
    # Check if current date is a weekend
    weekday = current_date.weekday()
    
    # If today is Monday (0), go back to Friday
    if weekday == 0:
        business_day = current_date - timedelta(days=3)
    # If today is Sunday (6), go back to Friday
    elif weekday == 6:
        business_day = current_date - timedelta(days=2)
    # If today is Saturday (5), go back to Friday
    elif weekday == 5:
        business_day = current_date - timedelta(days=1)
    # For Tuesday-Friday, yesterday is the business day
    else:
        business_day = current_date - timedelta(days=1)
    
    # Check if the business day is a holiday
    # If it is, go back one more day
    day, month = business_day.day, business_day.month
    if (day, month) in MARKET_HOLIDAYS:
        # If Friday was a holiday, NAV should be from Thursday
        if business_day.weekday() == 4:  # Friday
            business_day = business_day - timedelta(days=1)
        # If Thursday was also a holiday, keep going back
        while business_day.weekday() >= 5 or (business_day.day, business_day.month) in MARKET_HOLIDAYS:
            business_day = business_day - timedelta(days=1)
    
    return business_day


def should_refresh_nav(fund, check_history=False):
    """
    Check if NAV data should be refreshed based on:
    1. No current NAV
    2. NAV date is missing
    3. NAV is older than expected considering market holidays
    """
    # Check if current NAV exists
    if not fund.current_nav:
        return True, "No NAV data available"
    
    # Check if NAV date exists
    if not fund.nav_date:
        return True, "NAV date is missing"
    
    current_time = timezone.now().time()
    current_date = timezone.now().date()
    current_weekday = current_date.weekday()  # 0=Monday, 6=Sunday
    
    # Get the latest expected business day
    expected_nav_date = get_latest_business_day(current_date)
    
    # NAV updates typically happen after market hours (7-9 PM)
    # If it's past 8 PM on a weekday, we might expect today's NAV
    if current_weekday <= 4 and current_time.hour >= 20:  # Weekday and past 8 PM
        # Check if today is not a weekend
        if current_weekday < 5:  # Monday-Friday
            # Today's NAV might be available after 8 PM
            expected_nav_date = current_date
    
    # Check if NAV is older than expected
    if fund.nav_date < expected_nav_date:
        return True, f"NAV is outdated (from {fund.nav_date}, expected from {expected_nav_date})"
    
    # Only check history if explicitly requested (e.g., for charts)
    if check_history:
        from funds.models import NAVHistory
        history_count = NAVHistory.objects.filter(fund=fund).count()
        if history_count == 0:
            return True, "No NAV history available"
        
        # For history, we don't need daily updates - weekly is fine
        latest_history = NAVHistory.objects.filter(fund=fund).order_by('-date').first()
        if latest_history and latest_history.date < expected_nav_date - timedelta(days=7):
            return True, f"NAV history needs update (latest from {latest_history.date})"
    
    return False, "NAV data is current"


def auto_refresh_if_needed(request, fund, silent=False, fetch_history=False):
    """
    Automatically refresh NAV if needed and show appropriate message
    Set silent=True to suppress messages (used for bulk operations)
    Set fetch_history=True to also fetch NAV history (default: False)
    """
    # Check if auto-refresh is disabled
    from django.conf import settings
    if not getattr(settings, 'AUTO_REFRESH_ENABLED', True):
        return False
    
    should_refresh, reason = should_refresh_nav(fund, check_history=fetch_history)
    
    if should_refresh:
        try:
            from funds.services import fetch_fund_nav
            # Only fetch history if explicitly requested (e.g., for fund detail page)
            fetch_fund_nav(fund, fetch_history=fetch_history)
            fund.refresh_from_db()
            
            # Show info message about auto refresh (only if not silent)
            if not silent:
                messages.info(
                    request, 
                    f"Auto-refreshed NAV: {reason}"
                )
            logger.info(f"Auto-refreshed NAV for {fund.scheme_code}: {reason}")
            return True
        except Exception as e:
            logger.warning(f"Auto-refresh failed for {fund.scheme_code}: {e}")
            # Show warning only if it's a critical issue and not silent
            if not silent and not fund.current_nav:
                messages.warning(
                    request,
                    f"Unable to fetch latest NAV data. Please try manual refresh."
                )
    
    return False


def bulk_check_and_refresh(request, portfolio, fetch_history=False):
    """
    Check all funds in portfolio and refresh if needed
    Returns count of refreshed funds
    """
    # Check if auto-refresh is disabled
    from django.conf import settings
    if not getattr(settings, 'AUTO_REFRESH_ENABLED', True):
        return 0
    
    refreshed_count = 0
    holdings = portfolio.holdings.select_related('fund').all()
    
    # Only check during business hours or when likely to have new data
    current_hour = timezone.now().hour
    
    # Skip bulk refresh if business hours only is set and it's unlikely to have new NAV data
    if getattr(settings, 'AUTO_REFRESH_BUSINESS_HOURS_ONLY', True):
        # NAV updates typically happen between 7 PM - 10 PM on weekdays
        if current_hour < 19 or current_hour > 23:  # Before 7 PM or after 11 PM
            logger.debug(f"Skipping bulk refresh at hour {current_hour} - unlikely to have new NAV data")
            return 0
        
        # Also skip on weekends
        if timezone.now().weekday() >= 5:  # Saturday (5) or Sunday (6)
            logger.debug("Skipping bulk refresh on weekend")
            return 0
    
    # Collect funds that need refresh
    funds_to_refresh = []
    for pf in holdings:
        should_refresh, reason = should_refresh_nav(pf.fund, check_history=fetch_history)
        if should_refresh:
            funds_to_refresh.append((pf.fund, reason))
    
    # Refresh all needed funds silently
    for fund, reason in funds_to_refresh:
        if auto_refresh_if_needed(request, fund, silent=True, fetch_history=fetch_history):
            refreshed_count += 1
    
    # Show single consolidated message
    if refreshed_count > 0:
        messages.info(
            request,
            f"Auto-refreshed NAV for {refreshed_count} fund{'s' if refreshed_count > 1 else ''}"
        )
    
    return refreshed_count
