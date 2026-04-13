import requests
import logging
import json
import time
from django.utils import timezone
from datetime import datetime, date
from .models import MutualFund, NAVHistory, SeedStatus

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; MFTracker/1.0)',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
}
SEED_MAX_RETRIES = 4
SEED_RETRY_DELAY = 3   # seconds between retries


# ---------------------------------------------------------------------------
# Robust HTTP helpers
# ---------------------------------------------------------------------------

def _fetch_with_retry(url, max_retries=SEED_MAX_RETRIES, stream=False, timeout=60):
    """
    GET with exponential back-off retry.
    Uses streaming + full content read to survive IncompleteRead on flaky
    connections (common with the large mfapi.in fund-list payload).
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"GET {url}  (attempt {attempt}/{max_retries})")
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                stream=True,          # always stream so we control the read
            )
            resp.raise_for_status()

            # Read the whole body in chunks to avoid IncompleteRead on truncated
            # HTTP/1.1 chunked responses.
            chunks = []
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
            raw = b"".join(chunks)
            return raw

        except (requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            last_exc = exc
            wait = SEED_RETRY_DELAY * (2 ** (attempt - 1))
            logger.warning(f"Attempt {attempt} failed: {exc}. Retrying in {wait}s…")
            time.sleep(wait)

        except requests.exceptions.HTTPError as exc:
            # Non-retryable (4xx/5xx)
            raise

    raise last_exc


# ---------------------------------------------------------------------------
# Fund-list fetchers  (mfapi primary, AMFI fallback)
# ---------------------------------------------------------------------------

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
                    from datetime import datetime
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
                if isin and not obj.isin:
                    obj.isin = isin
                    dirty = True
                # Don't change is_active status on update
                if dirty:
                    to_update.append(obj)
                updated += 1
            else:
                # New funds start as inactive - store only essential data
                to_create.append(MutualFund(
                    scheme_code=code,
                    scheme_name=name,
                    isin=isin,
                    is_active=False
                ))
                created += 1

        if to_create:
            MutualFund.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            MutualFund.objects.bulk_update(to_update, ["scheme_name", "isin"])

    return created, updated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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


def fetch_fund_nav(fund, fetch_history=False):
    """Fetch current NAV (and optionally full history) for a fund."""
    try:
        # Always use full endpoint to ensure latest data
        import time
        timestamp = int(time.time())
        url = f"{MFAPI_BASE}/{fund.scheme_code}?_={timestamp}"
        raw = _fetch_with_retry(url, max_retries=3, timeout=20)
        data = json.loads(raw)
        logger.info(f"Fetched NAV data for {fund.scheme_code}: {len(data.get('data', []))} entries")
        
        # Get metadata from full response
        meta = data.get('meta', {})
        fund.amc = meta.get('fund_house', fund.amc or '')
        fund.category = meta.get('scheme_category', fund.category or '')
        fund.fund_type = meta.get('scheme_type', fund.fund_type or '')
        
        nav_data = data.get('data', [])

        if nav_data:
            latest = nav_data[0]
            try:
                nav_val = float(latest['nav'])
                date_str = latest['date']
                logger.info(f"NAV date string for {fund.scheme_code}: {date_str}")
                
                # Try different date formats
                for fmt in ['%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y']:
                    try:
                        nav_date = datetime.strptime(date_str, fmt).date()
                        logger.info(f"Successfully parsed date {date_str} with format {fmt}")
                        break
                    except ValueError:
                        continue
                else:
                    # If no format matched, use today's date as fallback
                    logger.warning(f"Could not parse date {date_str}, using today's date")
                    nav_date = date.today()
                
                fund.current_nav = nav_val
                fund.nav_date = nav_date
                fund.nav_last_updated = timezone.now()
                fund.save()
            except (ValueError, KeyError) as e:
                logger.warning(f"Could not parse NAV for {fund.scheme_code}: {e}")

        if fetch_history and nav_data:
            logger.info(f"Fetching history for {fund.scheme_code} with {len(nav_data)} entries")
            _save_nav_history(fund, nav_data)

    except Exception as e:
        logger.error(f"Failed to fetch NAV from mfapi.in for fund {fund.scheme_code}: {e}")
        logger.info(f"Trying AMFI fallback for fund {fund.scheme_code}")
        
        # Fallback: Try to get NAV from AMFI data
        try:
            _fetch_nav_from_amfi_fallback(fund)
            logger.info(f"Successfully fetched NAV from AMFI fallback for {fund.scheme_name}")
        except Exception as fallback_error:
            logger.error(f"Both mfapi.in and AMFI fallback failed for {fund.scheme_code}: {fallback_error}")
            raise e  # Raise the original error


def _fetch_nav_from_amfi_fallback(fund):
    """Fetch NAV from AMFI NAVAll.txt as fallback when mfapi.in is down."""
    logger.info(f"Fetching NAV from AMFI for {fund.scheme_code}")
    
    # Download AMFI NAV data
    raw = _fetch_with_retry(AMFI_NAV_URL, timeout=60)
    text = raw.decode("utf-8", errors="replace")
    
    # Parse the file to find the fund
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
            
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
            
            logger.info(f"Updated NAV from AMFI for {fund.scheme_name}: {nav_val} on {nav_date}")
            return
            
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing AMFI data for {fund.scheme_code}: {e}")
            continue
    
    # If we get here, the fund wasn't found
    raise ValueError(f"Fund {fund.scheme_code} not found in AMFI NAV data")


def _save_nav_history(fund, nav_data):
    """Bulk save NAV history entries."""
    existing_dates = set(
        NAVHistory.objects.filter(fund=fund).values_list('date', flat=True)
    )
    to_create = []
    for entry in nav_data:
        try:
            date_str = entry['date']
            nav = float(entry['nav'])
            
            # Try different date formats
            for fmt in ['%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y']:
                try:
                    d = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                # Skip if no format matched
                logger.warning(f"Skipping history entry with invalid date: {date_str}")
                continue
            
            if d not in existing_dates:
                to_create.append(NAVHistory(fund=fund, date=d, nav=nav))
        except (ValueError, KeyError):
            continue

    if to_create:
        NAVHistory.objects.bulk_create(to_create, ignore_conflicts=True)
        logger.info(f"Saved {len(to_create)} NAV history entries for {fund.scheme_code}")


def refresh_all_navs():
    """Refresh current NAV and history for all funds in portfolios. Called by scheduler."""
    from portfolio.models import PortfolioFund
    
    # Get only funds that are in user portfolios
    portfolio_funds = PortfolioFund.objects.select_related('fund').values_list('fund', flat=True).distinct()
    funds = MutualFund.objects.filter(id__in=portfolio_funds, is_active=True)
    
    logger.info(f"Scheduled refresh: Found {funds.count()} funds in portfolios")
    
    success = errors = 0
    for fund in funds:
        try:
            # Fetch history during scheduled refresh (runs at midnight when load is low)
            fetch_fund_nav(fund, fetch_history=True)
            success += 1
            time.sleep(0.2)  # Slightly higher rate limit for history fetch
        except Exception as e:
            errors += 1
            logger.error(f"NAV refresh error for {fund.scheme_code}: {e}")
    logger.info(f"NAV refresh complete: {success} success, {errors} errors.")
    return success, errors


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
            if 'expenseRatio' in fund_data:
                try:
                    fund.expense_ratio = float(fund_data['expenseRatio'])
                except:
                    pass
            
            fund.save(update_fields=[
                'amc', 'fund_category', 'fund_type', 'plan',
                'fund_manager', 'expense_ratio'
            ])
            
            return fund_data
            
    except Exception as e:
        logger.warning(f"Failed to fetch details for scheme {scheme_code} from mfapi.in: {e}")
    
    # Fallback: try to get from AMFI NAV data for basic info
    try:
        url = f"https://api.mfapi.in/mf/{scheme_code}"
        response = _fetch_with_retry(url)
        data = json.loads(response)
        
        if data.get('status') == 'success' and 'data' in data:
            fund_data = data['data']
            fund = MutualFund.objects.get(scheme_code=scheme_code)
            
            # Update basic NAV info
            if 'nav' in fund_data:
                try:
                    fund.current_nav = float(fund_data['nav'])
                except:
                    pass
            if 'date' in fund_data:
                from datetime import datetime
                try:
                    fund.nav_date = datetime.strptime(fund_data['date'], '%d-%b-%Y').date()
                except:
                    pass
            
            fund.save(update_fields=['current_nav', 'nav_date'])
            return fund_data
            
    except Exception as e:
        logger.error(f"Failed to fetch any details for scheme {scheme_code}: {e}")
    
    return None


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
