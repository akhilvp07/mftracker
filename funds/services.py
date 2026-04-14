import requests
import json
import logging
import time
from datetime import datetime, date
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from .models import MutualFund, NAVHistory, SeedStatus

logger = logging.getLogger(__name__)

# API endpoints
MFAPI_BASE = "https://api.mfapi.in/mf"
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# Constants
SEED_MAX_RETRIES = 4
SEED_RETRY_DELAY = 5  # seconds

# Global flags to track API status
_mfapi_down = False
_mfapi_down_time = None

# Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; MFTracker/1.0)',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
}


def _fetch_with_retry(url, max_retries=SEED_MAX_RETRIES, stream=False, timeout=60):
    """Fetch URL with retry logic."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers={}, timeout=timeout, stream=stream)
            response.raise_for_status()
            return response.text if not stream else response
        except requests.exceptions.RequestException as exc:
            if attempt == max_retries - 1:
                raise exc
            logger.warning(f"Retry {attempt + 1}/{max_retries} for {url}: {exc}")
            import time
            time.sleep(SEED_RETRY_DELAY)


def fetch_fund_nav(fund, fetch_history=False):
    """Fetch current NAV (and optionally full history) for a fund using round-robin API retry."""
    from decimal import Decimal
    
    # Define API sources in order of preference
    api_sources = [
        ('mfdata.in', _try_mfdata),
        ('mfapi.in', _try_mfapi),
        ('AMFI', _try_amfi)
    ]
    
    # Try each API source
    for api_name, api_func in api_sources:
        try:
            logger.info(f"Trying {api_name} for {fund.scheme_code}")
            if api_func(fund, fetch_history):
                logger.info(f"Successfully fetched NAV from {api_name} for {fund.scheme_code}")
                return  # Success, no need to try other APIs
        except Exception as e:
            logger.warning(f"{api_name} failed for {fund.scheme_code}: {e}")
            continue  # Try next API
    
    # If all APIs failed
    logger.error(f"All APIs failed for {fund.scheme_code}")


def _try_mfdata(fund, fetch_history):
    """Try fetching from mfdata.in API."""
    from .mfdata_service import fetch_fund_nav as fetch_from_mfdata
    
    # Determine if we should skip cache
    skip_cache = False
    if fetch_history:
        # Check if history is fresh enough
        from funds.models import NAVHistory
        latest_history = NAVHistory.objects.filter(fund=fund).order_by('-date').first()
        
        # Skip cache only if:
        # 1. No history exists, OR
        # 2. History is more than 1 day old, OR
        # 3. NAV was updated more recently than history
        if not latest_history:
            skip_cache = True
            logger.info(f"No history exists for {fund.scheme_code}, skipping cache")
        else:
            from datetime import timedelta
            now = timezone.now()
            
            # Check if history is stale (more than 1 day old)
            if (now.date() - latest_history.date) > timedelta(days=1):
                skip_cache = True
                logger.info(f"History is stale for {fund.scheme_code} (latest: {latest_history.date}), skipping cache")
            
            # Check if NAV was updated after latest history
            elif fund.nav_last_updated and fund.nav_last_updated > now - timedelta(hours=4):
                if fund.nav_last_updated.date() > latest_history.date:
                    skip_cache = True
                    logger.info(f"NAV updated after history for {fund.scheme_code}, skipping cache")
    
    nav_data = fetch_from_mfdata(fund.scheme_code, skip_cache=skip_cache)
    
    if nav_data:
        # Update fund with rich data from mfdata.in
        from decimal import Decimal
        fund.current_nav = Decimal(str(nav_data.get('nav', 0)))
        fund.nav_date = datetime.strptime(nav_data.get('nav_date'), '%Y-%m-%d').date()
        fund.nav_last_updated = timezone.now()
        
        # Update additional fields
        if 'expense_ratio' in nav_data and nav_data['expense_ratio']:
            fund.expense_ratio = Decimal(str(nav_data['expense_ratio']))
        
        if 'aum' in nav_data and nav_data['aum']:
            fund.aum = Decimal(str(nav_data['aum'] / 10000000))
        
        if 'day_change' in nav_data and nav_data['day_change'] is not None:
            fund.day_change = Decimal(str(nav_data['day_change']))
        
        if 'day_change_pct' in nav_data and nav_data['day_change_pct'] is not None:
            fund.day_change_pct = Decimal(str(nav_data['day_change_pct']))
        
        if 'morningstar' in nav_data and nav_data['morningstar'] is not None:
            fund.morningstar_rating = nav_data['morningstar']
        
        fund.save()
        
        # Cache for compatibility
        cache_key = f"nav_{fund.scheme_code}"
        cache_data = {
            'nav': fund.current_nav,
            'date': fund.nav_date,
            'updated_at': fund.nav_last_updated
        }
        cache.set(cache_key, cache_data, 14400)
        
        # Fetch history if requested
        if fetch_history:
            _fetch_nav_history_from_mfdata(fund)
            
            # Check if we got enough history (at least 200 entries for 1 year)
            from funds.models import NAVHistory
            history_count = NAVHistory.objects.filter(fund=fund).count()
            if history_count < 200:
                logger.info(f"mfdata.in returned only {history_count} history entries for {fund.scheme_code}, trying other APIs")
                return False  # Signal that we should try other APIs for more history
        
        return True
    
    return False


def _try_mfapi(fund, fetch_history):
    """Try fetching from mfapi.in API."""
    global _mfapi_down, _mfapi_down_time
    
    # Check if mfapi.in is known to be down
    if _mfapi_down and _mfapi_down_time and (timezone.now() - _mfapi_down_time).seconds < 300:
        logger.info(f"mfapi.in is known to be down, skipping")
        return False
    
    # Check cache first
    cache_key = f"nav_{fund.scheme_code}"
    cached_data = cache.get(cache_key)
    if cached_data and not fetch_history:
        logger.info(f"Using cached NAV data for {fund.scheme_code}")
        fund.current_nav = cached_data['nav']
        fund.nav_date = cached_data['date']
        fund.nav_last_updated = cached_data['updated_at']
        fund.save()
        return True
    
    try:
        import time
        timestamp = int(time.time())
        url = f"{MFAPI_BASE}/{fund.scheme_code}?_={timestamp}"
        raw = _fetch_with_retry(url, max_retries=3, timeout=20)
        data = json.loads(raw)
        
        # Reset down flag if successful
        if _mfapi_down:
            _mfapi_down = False
            _mfapi_down_time = None
            logger.info("mfapi.in is back online")
        
        nav_data = data.get('data', [])
        if nav_data:
            latest = nav_data[0]
            nav_val = float(latest['nav'])
            date_str = latest['date']
            
            # Parse date
            for fmt in ['%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y']:
                try:
                    nav_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                nav_date = date.today()
            
            fund.current_nav = nav_val
            fund.nav_date = nav_date
            fund.nav_last_updated = timezone.now()
            fund.save()
            
            # Trigger intelligent monitoring for NAV changes
            try:
                from alerts.intelligent_monitor import trigger_nav_monitoring
                # Run in background to avoid blocking
                from django.core.cache import cache
                cache_key = f"nav_monitor_trigger:{fund.scheme_code}"
                if not cache.get(cache_key):  # Avoid duplicate triggers
                    trigger_nav_monitoring(fund)
                    cache.set(cache_key, True, timeout=300)  # 5 minute cooldown
            except Exception as e:
                logger.warning(f"Failed to trigger NAV monitoring: {e}")
            
            # Cache
            cache_data = {
                'nav': nav_val,
                'date': nav_date,
                'updated_at': fund.nav_last_updated
            }
            cache.set(cache_key, cache_data, 14400)
            
            if fetch_history and nav_data:
                _save_nav_history(fund, nav_data)
            
            return True
            
    except Exception as e:
        # Mark as down if server error or timeout
        if '502' in str(e) or '503' in str(e) or 'timeout' in str(e).lower():
            _mfapi_down = True
            _mfapi_down_time = timezone.now()
            logger.warning("mfapi.in appears to be down, marking for 5 minutes")
        raise e
    
    return False


def _try_amfi(fund, fetch_history):
    """Try fetching from AMFI."""
    try:
        _fetch_nav_from_amfi_fallback(fund)
        return True
    except:
        return False


def _fetch_nav_from_amfi_fallback(fund):
    """Fetch NAV from AMFI when other APIs fail."""
    logger.info(f"Fetching NAV from AMFI for {fund.scheme_code}")
    
    # Download AMFI NAV file
    raw = _fetch_with_retry(AMFI_NAV_URL, timeout=60)
    
    # Parse the file line by line
    for line in raw.split('\n'):
        # Skip header lines
        if line.startswith('Scheme Code') or ';' not in line:
            continue
            
        parts = line.split(';')
        if len(parts) < 5:
            continue
            
        scheme_code = parts[0].strip()
        if scheme_code != str(fund.scheme_code):
            continue
            
        # Found the fund, extract NAV data
        try:
            nav_str = parts[4].strip()
            date_str = parts[5].strip()
            
            # Parse NAV
            nav_val = float(nav_str)
            
            # Parse date (DD-MMM-YYYY format)
            nav_date = datetime.strptime(date_str, '%d-%b-%Y').date()
            
            # Update fund
            fund.current_nav = nav_val
            fund.nav_date = nav_date
            fund.nav_last_updated = timezone.now()
            fund.save()
            
            # Cache the NAV data for 4 hours (even from AMFI)
            cache_key = f"nav_{fund.scheme_code}"
            cache_data = {
                'nav': nav_val,
                'date': nav_date,
                'updated_at': fund.nav_last_updated
            }
            cache.set(cache_key, cache_data, 14400)  # 4 hours = 14400 seconds
            logger.info(f"Cached NAV data from AMFI for {fund.scheme_code}")
            
            logger.info(f"Updated NAV from AMFI for {fund.scheme_name}: {nav_val} on {nav_date}")
            return
            
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing AMFI data for {fund.scheme_code}: {e}")
            continue
    
    # If we get here, the fund wasn't found
    raise ValueError(f"Fund {fund.scheme_code} not found in AMFI NAV data")


def _fetch_nav_history_from_mfdata(fund):
    """Fetch NAV history from mfdata.in and save to database."""
    from django.db import transaction, DatabaseError
    import time
    
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            from .mfdata_service import fetch_nav_history
            from datetime import datetime, timedelta
            
            # Calculate date range for 1 year
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365)
            
            # Try with date range first
            history_data = fetch_nav_history(
                fund.scheme_code, 
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                limit=500
            )
            
            # If date range returns insufficient data, fall back to limit
            if not history_data or len(history_data) < 200:
                history_data = fetch_nav_history(fund.scheme_code, limit=1000)
            
            if not history_data:
                return
            
            # Use transaction for batch operations
            with transaction.atomic():
                # Batch create/update history entries
                to_create = []
                to_update = []
                
                # Get existing dates for this fund
                existing_dates = set(
                    NAVHistory.objects.filter(fund=fund)
                    .values_list('date', flat=True)
                )
                
                for entry in history_data:
                    nav_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()
                    nav_value = Decimal(str(entry['nav']))
                    
                    if nav_date in existing_dates:
                        to_update.append({
                            'fund': fund,
                            'date': nav_date,
                            'nav': nav_value
                        })
                    else:
                        to_create.append(
                            NAVHistory(
                                fund=fund,
                                date=nav_date,
                                nav=nav_value
                            )
                        )
                
                # Bulk operations
                if to_create:
                    NAVHistory.objects.bulk_create(to_create, batch_size=100, ignore_conflicts=True)
                
                if to_update:
                    # Update existing entries
                    for item in to_update:
                        NAVHistory.objects.filter(
                            fund=item['fund'],
                            date=item['date']
                        ).update(nav=item['nav'])
                
                logger.info(f"Saved {len(history_data)} NAV history entries for {fund.scheme_code}")
                return  # Success, exit retry loop
            
        except DatabaseError as e:
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f"Database locked for {fund.scheme_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to fetch NAV history from mfdata.in for {fund.scheme_code}: {e}")
            break


def _save_nav_history(fund, nav_data):
    """Save NAV history data to database."""
    from django.db import transaction, DatabaseError
    from decimal import Decimal
    import time
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            to_create = []
            for entry in nav_data:
                try:
                    date_str = entry['date']
                    nav_str = entry['nav']
                    
                    # Parse date
                    for fmt in ['%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y']:
                        try:
                            nav_date = datetime.strptime(date_str, fmt).date()
                            break
                        except ValueError:
                            continue
                    else:
                        continue  # Skip if date can't be parsed
                    
                    # Parse NAV
                    nav_value = Decimal(nav_str)
                    
                    to_create.append(
                        NAVHistory(
                            fund=fund,
                            date=nav_date,
                            nav=nav_value
                        )
                    )
                    
                except (ValueError, KeyError):
                    continue
            
            if to_create:
                with transaction.atomic():
                    NAVHistory.objects.bulk_create(to_create, batch_size=100, ignore_conflicts=True)
                    logger.info(f"Saved {len(to_create)} NAV history entries for {fund.scheme_code}")
            return  # Success
            
        except DatabaseError as e:
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f"Database locked for {fund.scheme_code} history save, retry {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to save NAV history for {fund.scheme_code}: {e}")
            break


def refresh_all_nav_bulk(user_portfolio):
    """
    Refresh NAV for all funds using mfdata.in bulk endpoint.
    Falls back to individual refresh if bulk fails.
    """
    from portfolio.models import PortfolioFund
    
    logger.info(f"Starting bulk NAV refresh for portfolio {user_portfolio.name}")
    
    # Get all funds
    holdings = user_portfolio.holdings.select_related('fund').all()
    scheme_codes = [pf.fund.scheme_code for pf in holdings]
    
    if not scheme_codes:
        logger.warning("No funds found in portfolio")
        return
    
    # Try bulk refresh first
    try:
        from .mfdata_service import fetch_bulk_nav
        bulk_nav_data = fetch_bulk_nav(scheme_codes)
        
        if bulk_nav_data:
            logger.info(f"Successfully fetched bulk NAV data for {len(bulk_nav_data)} funds")
            
            # Update each fund
            updated_count = 0
            for pf in holdings:
                code = str(pf.fund.scheme_code)
                if code in bulk_nav_data:
                    nav_data = bulk_nav_data[code]
                    
                    # Update fund with rich data
                    from decimal import Decimal
                    pf.fund.current_nav = Decimal(str(nav_data.get('nav', 0)))
                    pf.fund.nav_date = datetime.strptime(nav_data.get('nav_date'), '%Y-%m-%d').date()
                    pf.fund.nav_last_updated = timezone.now()
                    
                    # Update all available fields from mfdata.in
                    if 'expense_ratio' in nav_data and nav_data['expense_ratio']:
                        pf.fund.expense_ratio = Decimal(str(nav_data['expense_ratio']))
                    
                    if 'aum' in nav_data and nav_data['aum']:
                        # Convert from absolute value to crores
                        aum_cr = nav_data['aum'] / 10000000
                        pf.fund.aum = Decimal(str(aum_cr))
                    
                    # Save day change information
                    if 'day_change' in nav_data and nav_data['day_change'] is not None:
                        pf.fund.day_change = Decimal(str(nav_data['day_change']))
                    
                    if 'day_change_pct' in nav_data and nav_data['day_change_pct'] is not None:
                        pf.fund.day_change_pct = Decimal(str(nav_data['day_change_pct']))
                    
                    # Save rating and classification
                    if 'morningstar' in nav_data and nav_data['morningstar'] is not None:
                        pf.fund.morningstar_rating = nav_data['morningstar']
                    
                    if 'family_id' in nav_data and nav_data['family_id'] is not None:
                        pf.fund.family_id = nav_data['family_id']
                    
                    if 'plan_type' in nav_data and nav_data['plan_type']:
                        pf.fund.plan_type = nav_data['plan_type']
                    
                    # Update/verify existing fields
                    if 'category' in nav_data and nav_data['category']:
                        pf.fund.category = nav_data['category']
                    
                    if 'amc_name' in nav_data and nav_data['amc_name']:
                        pf.fund.amc = nav_data['amc_name']
                    
                    pf.fund.save()
                    updated_count += 1
                    
                    logger.info(f"Updated {pf.fund.scheme_name}: NAV={pf.fund.current_nav} ({pf.fund.day_change_pct}%) | ER={pf.fund.expense_ratio}% | Rating={pf.fund.morningstar_rating}")
            
            logger.info(f"Bulk NAV refresh completed: {updated_count}/{len(holdings)} funds updated")
            return
        
    except Exception as e:
        logger.error(f"Bulk NAV refresh failed: {e}")
        logger.info("Falling back to individual fund refresh")
        
        # Fallback to individual refresh
        for pf in holdings:
            try:
                fetch_fund_nav(pf.fund, fetch_history=False)
            except Exception as e:
                logger.error(f"Individual refresh failed for {pf.fund.scheme_code}: {e}")


def refresh_all_nav(user_portfolio):
    """
    Refresh NAV for all funds in the portfolio.
    """
    funds = MutualFund.objects.filter(portfoliofund__portfolio=user_portfolio)
    
    logger.info(f"Starting NAV refresh for {funds.count()} funds")
    
    success = errors = 0
    for fund in funds:
        try:
            # Fetch history during scheduled refresh (runs at midnight when load is low)
            fetch_fund_nav(fund, fetch_history=True)
            success += 1
            import time
            time.sleep(0.5)  # Increased delay to reduce database contention
        except Exception as e:
            errors += 1
            logger.error(f"NAV refresh error for {fund.scheme_code}: {e}")
    logger.info(f"NAV refresh complete: {success} success, {errors} errors.")
    return success, errors


def search_funds(query, limit=20):
    """Search funds by name or scheme code with improved matching."""
    from django.db.models import Q
    import re
    
    # Search all funds, not just active ones, so users can find and add funds
    qs = MutualFund.objects.all()
    
    if query.isdigit():
        qs = qs.filter(Q(scheme_code=int(query)) | Q(scheme_name__icontains=query))
    else:
        # Create variations for better matching
        variations = []
        
        # Original query
        variations.append(query)
        
        # Handle common variations
        # 'smallcap' -> 'small cap'
        if 'smallcap' in query.lower():
            variations.append(query.lower().replace('smallcap', 'small cap'))
        # 'small cap' -> 'smallcap'
        if 'small cap' in query.lower():
            variations.append(query.lower().replace('small cap', 'smallcap'))
        # 'midcap' -> 'mid cap'
        if 'midcap' in query.lower():
            variations.append(query.lower().replace('midcap', 'mid cap'))
        # 'mid cap' -> 'midcap'
        if 'mid cap' in query.lower():
            variations.append(query.lower().replace('mid cap', 'midcap'))
        # 'largecap' -> 'large cap'
        if 'largecap' in query.lower():
            variations.append(query.lower().replace('largecap', 'large cap'))
        # 'large cap' -> 'largecap'
        if 'large cap' in query.lower():
            variations.append(query.lower().replace('large cap', 'largecap'))
        # 'bluechip' -> 'blue chip'
        if 'bluechip' in query.lower():
            variations.append(query.lower().replace('bluechip', 'blue chip'))
        # 'blue chip' -> 'bluechip'
        if 'blue chip' in query.lower():
            variations.append(query.lower().replace('blue chip', 'bluechip'))
        # 'equity' -> 'eq' (common abbreviation)
        if 'equity' in query.lower():
            variations.append(query.lower().replace('equity', 'eq'))
        # Note: Removed 'direct plan' variations since all funds are direct plans now
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for v in variations:
            if v not in seen:
                seen.add(v)
                unique_variations.append(v)
        
        # Build Q objects for all variations
        q_objects = Q()
        for variation in unique_variations:
            # For each variation, search for all words
            words = variation.split()
            word_q = Q()
            for word in words:
                word_q &= Q(scheme_name__icontains=word)
            q_objects |= word_q
        
        qs = qs.filter(q_objects)
    
    results = list(qs[:limit])
    
    # If we have fewer results than limit and user might be looking for non-direct plans,
    # we could fetch on-demand here in the future
    # For now, just return what we have
    
    return results


def fetch_fund_details(scheme_code):
    """
    Fetch detailed fund information when a fund is added to portfolio.
    This fetches additional data beyond the basic search info.
    
    Args:
        scheme_code: The scheme code of the fund
        
    Returns:
        dict: Detailed fund information or None if failed
    """
    from .models import MutualFund
    
    try:
        # Try mfapi.in first for detailed info
        url = f"https://api.mfapi.in/mf/{scheme_code}"
        response = _fetch_with_retry(url)
        data = json.loads(response)
        
        if data.get('status') == 'success' and 'data' in data:
            fund_data = data['data']
            
            # Update the fund in database with detailed info
            fund = MutualFund.objects.get(scheme_code=scheme_code)
            
            # Update fields that are available
            if 'amc' in fund_data:
                fund.amc = fund_data['amc'].get('name', '')
            if 'schemeCategory' in fund_data:
                fund.fund_category = fund_data['schemeCategory']
            if 'schemeType' in fund_data:
                fund.fund_type = fund_data['schemeType']
            if 'plan' in fund_data:
                fund.plan = fund_data['plan']
            if 'fundManager' in fund_data:
                fund.fund_manager = fund_data['fundManager']
            if 'investmentObjective' in fund_data:
                fund.investment_objective = fund_data['investmentObjective']
            
            fund.save()
            logger.info(f"Updated fund details for {scheme_code}")
            
            return fund_data
            
    except Exception as e:
        logger.error(f"Failed to fetch fund details for {scheme_code}: {e}")
    
    return None


def seed_fund_database(force=False):
    """Seed local DB with full AMFI fund list.

    Strategy:
      1. Try AMFI NAVAll.txt (primary - more reliable).
      2. If that fails, fall back to mfapi.in.
    """
    status, _ = SeedStatus.objects.get_or_create(pk=1)
    if status.status == 'done' and not force:
        logger.info("Database already seeded. Use force=True to re-seed.")
        return status

    status.status = 'running'
    status.error_message = ''
    status.save()

    funds_data = None
    source_used = "amfi"

    # --- Primary: AMFI NAVAll.txt ---
    try:
        funds_data = _fetch_funds_from_amfi()
        logger.info(f"AMFI returned {len(funds_data)} fund records")
    except Exception as exc:
        logger.warning(f"AMFI seed failed: {exc}. Trying mfapi.in fallback…")

    # --- Fallback: mfapi.in ---
    if not funds_data:
        try:
            funds_data = _fetch_funds_from_mfapi()
            source_used = "mfapi"
            logger.info(f"mfapi.in returned {len(funds_data)} fund records")
        except Exception as exc:
            msg = f"Both AMFI and mfapi.in fallback failed: {exc}"
            logger.error(msg)
            status.status = 'failed'
            status.error_message = msg
            status.save()
            raise RuntimeError(msg) from exc

    if not funds_data:
        msg = "No fund data returned from any source"
        status.status = 'failed'
        status.error_message = msg
        status.save()
        raise RuntimeError(msg)

    try:
        created, updated = _bulk_upsert_funds(funds_data)
        total = created + updated
        status.status = 'done'
        status.last_seeded = timezone.now()
        status.total_funds = total
        status.error_message = f"Source: {source_used}"
        status.save()
        logger.info(
            f"Seeding complete ({source_used}): "
            f"{created} created, {updated} updated, {total} total."
        )
        return status

    except Exception as exc:
        logger.error(f"DB upsert failed: {exc}")
        status.status = 'failed'
        status.error_message = str(exc)
        status.save()
        raise


def _fetch_funds_from_mfapi():
    """Return list of {schemeCode, schemeName} dicts from mfapi.in."""
    raw = _fetch_with_retry(MFAPI_BASE)
    return json.loads(raw)


def _fetch_funds_from_amfi():
    """
    Parse the AMFI NAVAll.txt file as a fallback fund-list source.

    File format (pipe-delimited, but actually semicolon in practice):
        Scheme Code;ISIN Div Payout/IDCW;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

    Section headers look like:
        Open Ended Schemes(Debt Scheme - Banking and PSU Fund)
    """
    logger.info("Falling back to AMFI NAVAll.txt for fund list…")
    raw = _fetch_with_retry(AMFI_NAV_URL, timeout=60)
    text = raw.decode("utf-8", errors="replace")

    funds = []
    current_amc = ""

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Data rows are semicolon-delimited; headers/AMC names have no semicolons.
        if ";" not in line:
            # Track AMC name (ignore category sub-headers like "Open Ended Schemes(…)")
            if not line.startswith("Open Ended") and not line.startswith("Close Ended") \
                    and not line.startswith("Interval") and "(" not in line:
                current_amc = line
            continue

        parts = line.split(";")
        if len(parts) < 4:
            continue

        try:
            scheme_code = int(parts[0].strip())
        except ValueError:
            continue  # skip any header rows that slipped through

        # Extract ISIN (prefer Div Payout/IDCW ISIN)
        isin = parts[1].strip() if len(parts) > 1 else ""
        if isin == "-" or not isin:
            isin = parts[2].strip() if len(parts) > 2 else ""  # Try Div Reinvestment ISIN
            
        scheme_name = parts[3].strip()
        
        # Extract NAV and date if available
        nav = None
        nav_date = None
        if len(parts) >= 6:
            try:
                nav_str = parts[4].strip()
                if nav_str and nav_str != 'NA':
                    nav = float(nav_str)
                
                date_str = parts[5].strip()
                if date_str and date_str != 'NA':
                    # Parse date in DD-MMM-YYYY format
                    try:
                        nav_date = datetime.strptime(date_str, '%d-%b-%Y').date()
                    except:
                        # Try other formats
                        try:
                            nav_date = datetime.strptime(date_str, '%d-%b-%y').date()
                        except:
                            pass
            except:
                pass
        
        if scheme_code and scheme_name:
            # Only store Direct Plan - Growth funds to optimize memory
            if 'direct plan' in scheme_name.lower() and 'growth' in scheme_name.lower():
                funds.append({
                    "schemeCode": scheme_code,
                    "schemeName": scheme_name,
                    "isin": isin,
                    # Skip AMC, NAV, and other data for optimization
                    # These will be fetched when fund is added to portfolio
                })

    logger.info(f"AMFI fallback: parsed {len(funds)} funds")
    return funds


def _bulk_upsert_funds(funds_data):
    """Upsert a list of fund dicts into MutualFund; return (created, updated)."""
    created = updated = 0
    
    # Process in batches for speed + memory efficiency
    BATCH = 500
    for i in range(0, len(funds_data), BATCH):
        batch = funds_data[i: i + BATCH]
        existing = {
            mf.scheme_code: mf
            for mf in MutualFund.objects.filter(
                scheme_code__in=[f["schemeCode"] for f in batch if f.get("schemeCode")]
            )
        }
        to_create = []
        to_update = []
        for item in batch:
            code = item.get("schemeCode")
            name = (item.get("schemeName") or "").strip()
            isin = (item.get("isin") or "").strip()
            
            if not code or not name:
                continue
                
            if code in existing:
                obj = existing[code]
                dirty = False
                if obj.scheme_name != name:
                    obj.scheme_name = name
                    dirty = True
                if obj.isin != isin:
                    obj.isin = isin
                    dirty = True
                if dirty:
                    to_update.append(obj)
                    updated += 1
            else:
                to_create.append(
                    MutualFund(
                        scheme_code=code,
                        scheme_name=name,
                        isin=isin,
                        is_active=False  # Will be activated when added to portfolio
                    )
                )
                created += 1
        
        # Bulk operations
        if to_create:
            MutualFund.objects.bulk_create(to_create, batch_size=100)
        if to_update:
            MutualFund.objects.bulk_update(
                to_update, 
                fields=['scheme_name', 'isin'], 
                batch_size=100
            )
    
    return created, updated
