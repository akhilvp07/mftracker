"""
mfdata.in API service for fetching comprehensive mutual fund data
"""
import json
import requests
import logging
from datetime import datetime, date
from decimal import Decimal
from django.core.cache import cache
from .models import MutualFund

logger = logging.getLogger(__name__)

# API Configuration
MFDATA_BASE = "https://mfdata.in/api/v1"
MFDATA_HEADERS = {
    'User-Agent': 'MFTracker/1.0',
    'Accept': 'application/json',
}

# Cache duration - 4 hours for NAV, 24 hours for fund details
NAV_CACHE_DURATION = 14400  # 4 hours
DETAILS_CACHE_DURATION = 86400  # 24 hours

# Global flag to track if API is down
_mfdata_down = False
_mfdata_down_time = None


def _fetch_with_retry(url, max_retries=3, timeout=5):
    """Fetch URL with retry logic."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=MFDATA_HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise e
            logger.warning(f"Retry {attempt + 1}/{max_retries} for {url}: {e}")
            import time
            time.sleep(1)


def fetch_fund_details(scheme_code):
    """Fetch comprehensive fund details from mfdata.in"""
    global _mfdata_down, _mfdata_down_time
    
    # Check cache first
    cache_key = f"mfdata_details_{scheme_code}"
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.info(f"Using cached fund details for {scheme_code}")
        return cached_data
    
    # Check if API is down
    if _mfdata_down and _mfdata_down_time and (datetime.now() - _mfdata_down_time).seconds < 300:
        logger.warning(f"mfdata.in is marked as down, skipping fetch for {scheme_code}")
        return None
    
    try:
        url = f"{MFDATA_BASE}/schemes/{scheme_code}"
        response_text = _fetch_with_retry(url)
        data = requests.models.Response().json() if isinstance(response_text, str) else response_text
        
        # Parse JSON
        import json
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            fund_data = data.get('data', {})
            
            # Cache the result
            cache.set(cache_key, fund_data, DETAILS_CACHE_DURATION)
            
            # Reset down flag if successful
            if _mfdata_down:
                _mfdata_down = False
                _mfdata_down_time = None
                logger.info("mfdata.in is back online")
            
            logger.info(f"Fetched fund details for {scheme_code} from mfdata.in")
            return fund_data
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to fetch fund details from mfdata.in for {scheme_code}: {e}")
        
        # Mark as down if server error or timeout
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower() or 'Read timed out' in str(e):
            _mfdata_down = True
            _mfdata_down_time = datetime.now()
            logger.warning("mfdata.in appears to be down, marking for 5 minutes")
        
        return None


def fetch_fund_nav(scheme_code, skip_cache=False):
    """Fetch current NAV from mfdata.in"""
    global _mfdata_down, _mfdata_down_time
    
    # Define cache key
    cache_key = f"mfdata_nav_{scheme_code}"
    
    # Check cache first (unless skipped)
    if not skip_cache:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Using cached NAV for {scheme_code}")
            return cached_data
    
    # Check if API is down
    if _mfdata_down and _mfdata_down_time and (datetime.now() - _mfdata_down_time).seconds < 300:
        logger.warning(f"mfdata.in is marked as down, skipping fetch for {scheme_code}")
        return None
    
    try:
        url = f"{MFDATA_BASE}/schemes/{scheme_code}/nav"
        response_text = _fetch_with_retry(url)
        
        # Parse JSON
        import json
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            nav_data = data.get('data', {})
            
            # Cache the result
            cache.set(cache_key, nav_data, NAV_CACHE_DURATION)
            
            # Reset down flag if successful
            if _mfdata_down:
                _mfdata_down = False
                _mfdata_down_time = None
                logger.info("mfdata.in is back online")
            
            logger.info(f"Fetched NAV for {scheme_code} from mfdata.in")
            return nav_data
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to fetch NAV from mfdata.in for {scheme_code}: {e}")
        
        # Mark as down if server error or timeout
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower() or 'Read timed out' in str(e):
            _mfdata_down = True
            _mfdata_down_time = datetime.now()
            logger.warning("mfdata.in appears to be down, marking for 5 minutes")
        
        return None


def fetch_bulk_nav(scheme_codes):
    """Fetch NAV for multiple schemes using mfdata.in bulk endpoint."""
    if not scheme_codes:
        return {}
    
    # Check cache first
    cache_key = f"mfdata_bulk_nav_{'_'.join(map(str, scheme_codes))}"
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.info(f"Using cached bulk NAV for {len(scheme_codes)} schemes")
        return cached_data
    
    # Use bulk endpoint
    try:
        # Convert to strings and join
        codes_str = ','.join(str(code) for code in scheme_codes)
        url = f"{MFDATA_BASE}/schemes/batch/lookup?scheme_codes={codes_str}"
        response_text = _fetch_with_retry(url)
        
        # Parse JSON
        import json
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            nav_data = data.get('data', [])
            
            # Convert to dict for easier lookup
            nav_dict = {}
            for item in nav_data:
                # The API returns 'amfi_code'
                code = item.get('amfi_code')
                if code:
                    nav_dict[str(code)] = item
            
            # Cache the result
            cache.set(cache_key, nav_dict, NAV_CACHE_DURATION)
            
            logger.info(f"Fetched bulk NAV for {len(nav_dict)} schemes from mfdata.in")
            return nav_dict
        
        logger.error(f"Bulk endpoint returned error: {data}")
        return {}
        
    except Exception as e:
        logger.error(f"Failed to fetch bulk NAV from mfdata.in: {e}")
        
        # Mark as down if server error or timeout
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower() or 'Read timed out' in str(e):
            _mfdata_down = True
            _mfdata_down_time = datetime.now()
            logger.warning("mfdata.in appears to be down, marking for 5 minutes")
        
        return {}


def fetch_nav_history(scheme_code, start_date=None, end_date=None, limit=100):
    """Fetch historical NAV data"""
    try:
        url = f"{MFDATA_BASE}/schemes/{scheme_code}/nav/history"
        params = {}
        
        if start_date:
            params['start'] = start_date
        if end_date:
            params['end'] = end_date
        params['limit'] = limit
        
        # Build URL with params
        if params:
            query_string = '&'.join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query_string}"
        
        response_text = _fetch_with_retry(url)
        
        # Parse JSON
        import json
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            # The API returns a dict with 'data' key containing the history
            response_data = data.get('data', {})
            if isinstance(response_data, dict) and 'data' in response_data:
                return response_data['data']
            elif isinstance(response_data, list):
                return response_data
            else:
                return []
        
        return []
        
    except Exception as e:
        logger.error(f"Failed to fetch NAV history from mfdata.in for {scheme_code}: {e}")
        return []


def update_fund_from_mfdata(fund):
    """Update fund model with data from mfdata.in"""
    details = fetch_fund_details(fund.scheme_code)
    
    if not details:
        return False
    
    try:
        # Update basic info
        fund.nav = Decimal(str(details.get('nav', 0)))
        fund.nav_date = datetime.strptime(details.get('nav_date'), '%Y-%m-%d').date()
        fund.nav_last_updated = datetime.now()
        
        # Update additional metadata if available
        if 'expense_ratio' in details:
            fund.expense_ratio = Decimal(str(details.get('expense_ratio', 0)))
        
        if 'category' in details:
            fund.category = details.get('category', fund.category or '')
        
        if 'amc_name' in details:
            fund.amc = details.get('amc_name', fund.amc or '')
        
        # Store additional data in a JSON field if needed
        # You could add a JSONField to store extra metadata
        
        fund.save()
        logger.info(f"Updated fund {fund.scheme_name} from mfdata.in")
        return True
        
    except Exception as e:
        logger.error(f"Error updating fund {fund.scheme_code} from mfdata.in: {e}")
        return False


def fetch_scheme_full_profile(scheme_code):
    """Fetch complete scheme profile including returns, ratios, and fund info."""
    try:
        url = f"{MFDATA_BASE}/schemes/{scheme_code}"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch scheme profile for {scheme_code}: {e}")
        return None


def fetch_scheme_returns(scheme_code):
    """Fetch returns with category ranks for 1m, 3m, 6m, 1y, 3y, 5y periods."""
    try:
        url = f"{MFDATA_BASE}/schemes/{scheme_code}/returns"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch returns for {scheme_code}: {e}")
        return None


def fetch_family_holdings(family_id, month=None, holding_type=None):
    """Fetch portfolio holdings (equity, debt, other) for a fund family."""
    from django.utils import timezone
    
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/holdings"
        params = []
        if month:
            params.append(f"month={month}")
        if holding_type:
            params.append(f"holding_type={holding_type}")
        if params:
            url += "?" + "&".join(params)
        
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            holdings = data.get('data', {})
            
            # Add metadata
            holdings['fetched_at'] = timezone.now().isoformat()
            if month:
                holdings['month'] = month
            
            # Check if API allocation percentages are reasonable (allow small rounding errors)
            api_total = (holdings.get('equity_pct', 0) + 
                        holdings.get('debt_pct', 0) + 
                        holdings.get('other_pct', 0))
            
            # If API gives reasonable percentages (total <= 110%), use them
            # Allow up to 10% for rounding errors and data inconsistencies
            # But reject clearly invalid data like 184%
            if api_total <= 110:
                logger.debug(f"Using API allocation percentages: total={api_total}%")
                return holdings
            
            logger.warning(f"API allocation percentages invalid (total={api_total}%), calculating from holdings")
            
            # Otherwise, calculate from actual holdings
            equity_weight = 0
            debt_weight = 0
            other_weight = 0
            
            # Sum up weights from equity holdings
            if holdings.get('equity_holdings'):
                for h in holdings['equity_holdings']:
                    equity_weight += h.get('weight_pct', 0)
            
            # Sum up weights from debt holdings (excluding None entries which are likely cash)
            if holdings.get('debt_holdings'):
                for h in holdings['debt_holdings']:
                    if h.get('stock_name') and h.get('stock_name') != 'None':
                        debt_weight += h.get('weight_pct', 0)
            
            # Sum up weights from other holdings
            if holdings.get('other_holdings'):
                for h in holdings['other_holdings']:
                    other_weight += h.get('weight_pct', 0)
            
            # Update the allocation with calculated values
            holdings['equity_pct'] = round(equity_weight, 2)
            holdings['debt_pct'] = round(debt_weight, 2)
            holdings['other_pct'] = round(other_weight, 2)
            
            calculated_total = equity_weight + debt_weight + other_weight
            logger.info(f"Calculated allocation percentages: equity={equity_weight:.2f}%, debt={debt_weight:.2f}%, other={other_weight:.2f}%, total={calculated_total:.2f}%")
            
            # If other_pct is negligible or negative, set it to 0
            if holdings['other_pct'] < 0.01:
                holdings['other_pct'] = 0
                logger.debug("Setting other_pct to 0 as it's negligible")
            
            # Trigger intelligent monitoring for holdings changes
            try:
                from alerts.intelligent_monitor import trigger_holdings_monitoring
                from django.core.cache import cache
                cache_key = f"holdings_monitor_trigger:{family_id}"
                if not cache.get(cache_key):  # Avoid duplicate triggers
                    # Find a fund with this family_id to trigger monitoring
                    from funds.models import MutualFund
                    fund = MutualFund.objects.filter(family_id=family_id, is_active=True).first()
                    if fund:
                        trigger_holdings_monitoring(fund)
                        cache.set(cache_key, True, timeout=3600)  # 1 hour cooldown
            except Exception as e:
                logger.warning(f"Failed to trigger holdings monitoring: {e}")
            
            return holdings
        return None
    except Exception as e:
        logger.error(f"Failed to fetch holdings for family {family_id}: {e}")
        return None


def fetch_family_sectors(family_id):
    """Fetch sector allocation for a fund family."""
    from django.utils import timezone
    
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/sectors"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            sectors = data.get('data', [])
            # Add metadata
            if isinstance(sectors, list):
                # If sectors is a list, add metadata to each sector
                for sector in sectors:
                    sector['fetched_at'] = timezone.now().isoformat()
            else:
                # If sectors is a dict, add metadata at top level
                sectors['fetched_at'] = timezone.now().isoformat()
            return sectors
        return []
    except Exception as e:
        logger.error(f"Failed to fetch sectors for family {family_id}: {e}")
        return []


def fetch_family_managers(family_id):
    """Fetch fund manager details including tenure."""
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/managers"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch managers for family {family_id}: {e}")
        return None


def fetch_family_ratios(family_id):
    """Fetch valuation, risk, return, and efficiency ratios."""
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/ratios"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch ratios for family {family_id}: {e}")
        return None


def fetch_family_risk(family_id):
    """Fetch risk analysis including drawdown, capture ratios, analyst rating."""
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/risk"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch risk data for family {family_id}: {e}")
        return None


def fetch_family_annual_returns(family_id):
    """Fetch year-by-year returns with growth of 10K."""
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/annual-returns"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch annual returns for family {family_id}: {e}")
        return None


def fetch_family_credit_quality(family_id):
    """Fetch credit quality breakdown for debt funds."""
    try:
        url = f"{MFDATA_BASE}/families/{family_id}/credit-quality"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch credit quality for family {family_id}: {e}")
        return None


def compare_schemes(scheme_codes):
    """Compare up to 10 schemes side-by-side."""
    try:
        codes_str = ",".join(map(str, scheme_codes))
        url = f"{MFDATA_BASE}/compare?scheme_codes={codes_str}"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to compare schemes: {e}")
        return None


def fetch_portfolio_overlap(scheme_codes):
    """Find common stocks between 2-5 scheme portfolios."""
    try:
        codes_str = ",".join(map(str, scheme_codes))
        url = f"{MFDATA_BASE}/overlap?scheme_codes={codes_str}"
        response_text = _fetch_with_retry(url)
        data = json.loads(response_text)
        
        if data.get('status') == 'success':
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch portfolio overlap: {e}")
        return None


def fetch_and_update_fund_complete(fund):
    """
    Fetch all available data from mfdata.in and update the fund model.
    This includes: profile, returns, ratios, risk metrics, manager info.
    """
    from decimal import Decimal
    from django.utils import timezone
    
    updated_fields = []
    
    try:
        # 1. Fetch full scheme profile
        profile = fetch_scheme_full_profile(fund.scheme_code)
        if profile:
            # Basic info
            if profile.get('nav'):
                fund.current_nav = Decimal(str(profile['nav']))
                updated_fields.append('current_nav')
            if profile.get('nav_date'):
                fund.nav_date = datetime.strptime(profile['nav_date'], '%Y-%m-%d').date()
                updated_fields.append('nav_date')
            if profile.get('aum'):
                # AUM is in absolute value, convert to crores
                fund.aum = Decimal(str(profile['aum'] / 10000000))
                updated_fields.append('aum')
            if profile.get('expense_ratio'):
                fund.expense_ratio = Decimal(str(profile['expense_ratio']))
                updated_fields.append('expense_ratio')
            if profile.get('category'):
                fund.category = profile['category']
                updated_fields.append('category')
            if profile.get('amc_name'):
                fund.amc = profile['amc_name']
                updated_fields.append('amc')
            if profile.get('morningstar'):
                fund.morningstar_rating = profile['morningstar']
                updated_fields.append('morningstar_rating')
            if profile.get('family_id'):
                fund.family_id = profile['family_id']
                updated_fields.append('family_id')
            if profile.get('plan_type'):
                fund.plan_type = profile['plan_type']
                updated_fields.append('plan_type')
            if profile.get('exit_load'):
                fund.exit_load = profile['exit_load'].replace('<br/>', ' | ')
                updated_fields.append('exit_load')
            if profile.get('min_lumpsum'):
                fund.min_investment = Decimal(str(profile['min_lumpsum']))
                updated_fields.append('min_investment')
            if profile.get('min_sip'):
                fund.min_sip = Decimal(str(profile['min_sip']))
                updated_fields.append('min_sip')
            if profile.get('day_change'):
                fund.day_change = Decimal(str(profile['day_change']))
                updated_fields.append('day_change')
            if profile.get('day_change_pct'):
                fund.day_change_pct = Decimal(str(profile['day_change_pct']))
                updated_fields.append('day_change_pct')
            if profile.get('launch_date'):
                fund.start_date = datetime.strptime(profile['launch_date'], '%Y-%m-%d').date()
                updated_fields.append('start_date')
            
            # Returns from profile (flat structure)
            returns = profile.get('returns', {})
            if returns:
                if returns.get('return_1m') is not None:
                    fund.return_1m = Decimal(str(returns['return_1m']))
                    updated_fields.append('return_1m')
                if returns.get('return_3m') is not None:
                    fund.return_3m = Decimal(str(returns['return_3m']))
                    updated_fields.append('return_3m')
                if returns.get('return_6m') is not None:
                    fund.return_6m = Decimal(str(returns['return_6m']))
                    updated_fields.append('return_6m')
                if returns.get('return_1y') is not None:
                    fund.return_1y = Decimal(str(returns['return_1y']))
                    updated_fields.append('return_1y')
                if returns.get('return_3y') is not None:
                    fund.return_3y = Decimal(str(returns['return_3y']))
                    updated_fields.append('return_3y')
                if returns.get('return_5y') is not None:
                    fund.return_5y = Decimal(str(returns['return_5y']))
                    updated_fields.append('return_5y')
                if returns.get('return_inception') is not None:
                    fund.return_since_inception = Decimal(str(returns['return_inception']))
                    updated_fields.append('return_since_inception')
                # Ranks
                if returns.get('rank_1y') is not None:
                    fund.rank_1y = returns['rank_1y']
                    updated_fields.append('rank_1y')
                if returns.get('rank_3y') is not None:
                    fund.rank_3y = returns['rank_3y']
                    updated_fields.append('rank_3y')
                if returns.get('rank_5y') is not None:
                    fund.rank_5y = returns['rank_5y']
                    updated_fields.append('rank_5y')
                if returns.get('rank_total') is not None:
                    fund.total_in_category = returns['rank_total']
                    updated_fields.append('total_in_category')
            
            # Ratios from profile (nested structure)
            ratios = profile.get('ratios', {})
            if ratios:
                # Valuation ratios
                valuation = ratios.get('valuation', {})
                if valuation.get('pe_ratio') is not None:
                    fund.pe_ratio = Decimal(str(valuation['pe_ratio']))
                    updated_fields.append('pe_ratio')
                if valuation.get('pb_ratio') is not None:
                    fund.pb_ratio = Decimal(str(valuation['pb_ratio']))
                    updated_fields.append('pb_ratio')
                if valuation.get('dividend_yield') is not None:
                    fund.dividend_yield = Decimal(str(valuation['dividend_yield']))
                    updated_fields.append('dividend_yield')
                
                # Risk ratios
                risk = ratios.get('risk', {})
                if risk.get('std_deviation') is not None:
                    fund.std_deviation = Decimal(str(risk['std_deviation']))
                    updated_fields.append('std_deviation')
                if risk.get('beta') is not None:
                    fund.beta = Decimal(str(risk['beta']))
                    updated_fields.append('beta')
                if risk.get('sortino_ratio') is not None:
                    fund.sortino_ratio = Decimal(str(risk['sortino_ratio']))
                    updated_fields.append('sortino_ratio')
                if risk.get('r_squared') is not None:
                    fund.r_squared = Decimal(str(risk['r_squared']))
                    updated_fields.append('r_squared')
                
                # Return ratios
                return_ratios = ratios.get('returns', {})
                if return_ratios.get('sharpe_ratio') is not None:
                    fund.sharpe_ratio = Decimal(str(return_ratios['sharpe_ratio']))
                    updated_fields.append('sharpe_ratio')
                if return_ratios.get('jensens_alpha') is not None:
                    fund.alpha = Decimal(str(return_ratios['jensens_alpha']))
                    updated_fields.append('alpha')
                if return_ratios.get('treynor_ratio') is not None:
                    fund.treynor_ratio = Decimal(str(return_ratios['treynor_ratio']))
                    updated_fields.append('treynor_ratio')
        
        # Update timestamp
        fund.nav_last_updated = timezone.now()
        fund.save()
        
        logger.info(f"Updated {len(updated_fields)} fields for {fund.scheme_name} from mfdata.in")
        return True
        
    except Exception as e:
        logger.error(f"Error fetching complete data for {fund.scheme_code}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def clear_mfdata_cache(scheme_code=None):
    """Clear mfdata cache for a specific fund or all funds"""
    if scheme_code:
        cache.delete(f"mfdata_details_{scheme_code}")
        cache.delete(f"mfdata_nav_{scheme_code}")
        logger.info(f"Cleared mfdata cache for fund {scheme_code}")
    else:
        # Clear all mfdata caches (pattern matching would require Redis backend)
        logger.info("mfdata cache will be cleared as funds are updated")
