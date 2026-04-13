"""
mfdata.in API service for fetching comprehensive mutual fund data
"""
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


def _fetch_with_retry(url, max_retries=3, timeout=10):
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
        
        # Mark as down if server error
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower():
            _mfdata_down = True
            _mfdata_down_time = datetime.now()
            logger.warning("mfdata.in appears to be down, marking for 5 minutes")
        
        return None


def fetch_fund_nav(scheme_code):
    """Fetch current NAV from mfdata.in"""
    global _mfdata_down, _mfdata_down_time
    
    # Check cache first
    cache_key = f"mfdata_nav_{scheme_code}"
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.info(f"Using cached NAV for {scheme_code}")
        return cached_data
    
    # Check if API is down
    if _mfdata_down and _mfdata_down_time and (datetime.now() - _mfdata_down_time).seconds < 300:
        logger.warning(f"mfdata.in is marked as down, using fallback for {scheme_code}")
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
        
        # Mark as down if server error
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower():
            _mfdata_down = True
            _mfdata_down_time = datetime.now()
            logger.warning("mfdata.in appears to be down, marking for 5 minutes")
        
        return None


def fetch_bulk_nav(scheme_codes):
    """Fetch NAV for multiple schemes using parallel requests."""
    if not scheme_codes:
        return {}
    
    # Check cache first
    cache_key = f"mfdata_bulk_nav_{'_'.join(map(str, scheme_codes))}"
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.info(f"Using cached bulk NAV for {len(scheme_codes)} schemes")
        return cached_data
    
    # Try actual bulk endpoint first
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
                # The API might return 'amfi_code' or 'scheme_code'
                code = item.get('amfi_code') or item.get('scheme_code')
                if code:
                    nav_dict[str(code)] = item
            
            # Cache the result
            cache.set(cache_key, nav_dict, NAV_CACHE_DURATION)
            
            logger.info(f"Fetched bulk NAV for {len(nav_dict)} schemes from mfdata.in")
            return nav_dict
        
    except Exception as e:
        logger.warning(f"Bulk endpoint failed, trying parallel requests: {e}")
    
    # Fallback to parallel requests
    return fetch_bulk_nav_parallel(scheme_codes)


def fetch_bulk_nav_parallel(scheme_codes, max_workers=10):
    """Fetch NAV for multiple schemes using parallel requests."""
    import concurrent.futures
    import json
    
    if not scheme_codes:
        return {}
    
    logger.info(f"Fetching NAV for {len(scheme_codes)} schemes using parallel requests")
    
    def fetch_single_nav(scheme_code):
        """Fetch NAV for a single scheme."""
        try:
            url = f"{MFDATA_BASE}/schemes/{scheme_code}/nav"
            response_text = _fetch_with_retry(url, max_retries=2, timeout=5)
            data = json.loads(response_text)
            
            if data.get('status') == 'success':
                return data.get('data')
        except Exception as e:
            logger.warning(f"Failed to fetch NAV for {scheme_code}: {e}")
        return None
    
    # Use ThreadPoolExecutor for parallel requests
    nav_dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all requests
        future_to_code = {executor.submit(fetch_single_nav, code): code for code in scheme_codes}
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_code):
            code = future_to_code[future]
            try:
                nav_data = future.result()
                if nav_data:
                    nav_dict[str(code)] = nav_data
            except Exception as e:
                logger.error(f"Error processing result for {code}: {e}")
    
    # Cache the result
    cache_key = f"mfdata_bulk_nav_{'_'.join(map(str, scheme_codes))}"
    cache.set(cache_key, nav_dict, NAV_CACHE_DURATION)
    
    logger.info(f"Fetched NAV for {len(nav_dict)}/{len(scheme_codes)} schemes using parallel requests")
    return nav_dict


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
            return data.get('data', [])
        
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


def clear_mfdata_cache(scheme_code=None):
    """Clear mfdata cache for a specific fund or all funds"""
    if scheme_code:
        cache.delete(f"mfdata_details_{scheme_code}")
        cache.delete(f"mfdata_nav_{scheme_code}")
        logger.info(f"Cleared mfdata cache for fund {scheme_code}")
    else:
        # Clear all mfdata caches (pattern matching would require Redis backend)
        logger.info("mfdata cache will be cleared as funds are updated")
