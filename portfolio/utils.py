"""
Utility functions for portfolio management
"""
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib import messages
from django.core.cache import cache
import logging
import requests

logger = logging.getLogger(__name__)


def fetch_market_holidays(year=None):
    """
    Fetch market holidays from Upstox API for a given year.
    Returns a list of dates (as date objects) where NSE is closed.
    Caches for 30 days to avoid excessive API calls.
    """
    if year is None:
        year = timezone.now().year
    
    cache_key = f'market_holidays_{year}'
    cached_holidays = cache.get(cache_key)
    if cached_holidays is not None:
        return cached_holidays
    
    try:
        url = f"https://api.upstox.com/v2/market/holidays/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') == 'success':
            holidays = []
            for holiday in data.get('data', []):
                # Only consider holidays where NSE is closed
                if 'NSE' in holiday.get('closed_exchanges', []):
                    holiday_date = datetime.strptime(holiday['date'], '%Y-%m-%d').date()
                    holidays.append(holiday_date)
            
            # Cache for 30 days (holidays don't change within a year)
            cache.set(cache_key, holidays, 2592000)  # 30 days = 2592000 seconds
            logger.info(f"Fetched {len(holidays)} market holidays for {year}")
            return holidays
        else:
            logger.warning(f"Upstox API returned non-success status: {data}")
            return []
    except Exception as e:
        logger.error(f"Failed to fetch market holidays from Upstox: {e}")
        return []


def get_latest_business_day(current_date):
    """
    Get the latest business day considering weekends and market holidays
    """
    # Fetch market holidays for the current year
    market_holidays = fetch_market_holidays(current_date.year)
    
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
    
    # Check if the business day is a market holiday
    # If it is, go back one more day
    while business_day in market_holidays:
        business_day = business_day - timedelta(days=1)
    
    return business_day


def should_refresh_nav(fund, check_history=False, latest_business_day=None):
    """
    Check if NAV data should be refreshed based on:
    1. No current NAV
    2. NAV date is missing
    3. NAV is stale considering weekends and market hours
    
    Args:
        fund: The fund to check
        check_history: Whether to also check NAV history
        latest_business_day: Optional pre-calculated latest business day (for optimization)
    """
    # Import the helper function to use consistent logic
    from funds.services import is_nav_data_stale
    
    # Check if current NAV exists
    if not fund.current_nav:
        return True, "No NAV data available"
    
    # Check if NAV date exists
    if not fund.nav_date:
        return True, "NAV date is missing"
    
    current_date = timezone.now().date()
    current_weekday = current_date.weekday()  # 0=Monday, 6=Sunday
    
    # Calculate latest business day if not provided
    if latest_business_day is None:
        latest_business_day = get_latest_business_day(current_date)
    
    # Check if NAV is stale using the same logic as bulk refresh
    if is_nav_data_stale(fund.nav_date, current_date):
        # For more specific messaging, calculate expected date
        current_time = timezone.now().time()
        
        expected_nav_date = latest_business_day
        
        # NAV updates typically happen after market hours (7-9 PM)
        # Only expect today's NAV after 9 PM on weekdays (more conservative)
        if current_weekday <= 4 and current_time.hour >= 21:  # Weekday and past 9 PM
            # Check if today is not a weekend
            if current_weekday < 5:  # Monday-Friday
                # Today's NAV might be available after 9 PM
                expected_nav_date = current_date
        
        # Only consider stale if the NAV is 1+ days older than expected
        days_diff = (expected_nav_date - fund.nav_date).days
        if days_diff >= 1:
            return True, f"NAV is outdated (from {fund.nav_date}, expected from {expected_nav_date})"
    
    # Only check history if explicitly requested (e.g., for charts)
    if check_history:
        from funds.models import NAVHistory
        if not NAVHistory.objects.filter(fund=fund).exists():
            return True, "No NAV history available"
        
        # For history, we don't need daily updates - weekly is fine
        latest_history = NAVHistory.objects.filter(fund=fund).order_by('-date').first()
        if latest_history and latest_history.date < current_date - timedelta(days=7):
            return True, f"NAV history needs update (latest from {latest_history.date})"
    
    return False, "NAV data is current"


def auto_refresh_if_needed(request, fund, silent=False, fetch_history=False, latest_business_day=None):
    """
    Automatically refresh NAV if needed and show appropriate message
    Set silent=True to suppress messages (used for bulk operations)
    Set fetch_history=True to also fetch NAV history (default: False)
    Args:
        latest_business_day: Optional pre-calculated latest business day (for optimization)
    """
    # Check if auto-refresh is disabled
    from django.conf import settings
    if not getattr(settings, 'AUTO_REFRESH_ENABLED', True):
        return False
    
    should_refresh, reason = should_refresh_nav(fund, check_history=fetch_history, latest_business_day=latest_business_day)
    
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
    current_date = timezone.now().date()
    current_hour = timezone.now().hour
    current_weekday = current_date.weekday()
    
    # Skip bulk refresh if business hours only is set and it's unlikely to have new NAV data
    if getattr(settings, 'AUTO_REFRESH_BUSINESS_HOURS_ONLY', True):
        # NAV updates typically happen between 7 PM - 10 PM on weekdays
        if current_hour < 19 or current_hour > 23:  # Before 7 PM or after 11 PM
            logger.debug(f"Skipping bulk refresh at hour {current_hour} - unlikely to have new NAV data")
            return 0
        
        # Also skip on weekends
        if current_weekday >= 5:  # Saturday (5) or Sunday (6)
            logger.debug("Skipping bulk refresh on weekend")
            return 0
    latest_business_day = get_latest_business_day(current_date)
    
    # Collect funds that need refresh
    funds_to_refresh = []
    for pf in holdings:
        should_refresh, reason = should_refresh_nav(pf.fund, check_history=fetch_history, latest_business_day=latest_business_day)
        if should_refresh:
            funds_to_refresh.append((pf.fund, reason))
    
    # Refresh all needed funds silently
    for fund, reason in funds_to_refresh:
        if auto_refresh_if_needed(request, fund, silent=True, fetch_history=fetch_history, latest_business_day=latest_business_day):
            refreshed_count += 1
    
    # Show single consolidated message
    if refreshed_count > 0:
        messages.info(
            request,
            f"Auto-refreshed NAV for {refreshed_count} fund{'s' if refreshed_count > 1 else ''}"
        )
    
    return refreshed_count
