import requests
import logging
import json
import io
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

    File format (pipe-delimited):
        Scheme Code|ISIN Div Payout/IDCW|ISIN Div Reinvestment|Scheme Name|Net Asset Value|Date

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
            if not line.startswith("Open Ended") and not line.startswith("Close Ended")                     and not line.startswith("Interval") and "(" not in line:
                current_amc = line
            continue

        parts = line.split(";")
        if len(parts) < 4:
            continue

        try:
            scheme_code = int(parts[0].strip())
        except ValueError:
            continue  # skip any header rows that slipped through

        scheme_name = parts[3].strip()
        if scheme_code and scheme_name:
            funds.append({
                "schemeCode": scheme_code,
                "schemeName": scheme_name,
                "amc": current_amc,
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
            amc  = (item.get("amc") or "").strip()
            if not code or not name:
                continue
            if code in existing:
                obj = existing[code]
                dirty = False
                if obj.scheme_name != name:
                    obj.scheme_name = name
                    dirty = True
                if amc and obj.amc != amc:
                    obj.amc = amc
                    dirty = True
                if dirty:
                    to_update.append(obj)
                updated += 1
            else:
                to_create.append(MutualFund(scheme_code=code, scheme_name=name, amc=amc))
                created += 1

        if to_create:
            MutualFund.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            MutualFund.objects.bulk_update(to_update, ["scheme_name", "amc"])

    return created, updated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_fund_database(force=False):
    """Seed local DB with full AMFI fund list.

    Strategy:
      1. Try mfapi.in (with retry + stream).
      2. If that fails, fall back to AMFI NAVAll.txt.
    """
    status, _ = SeedStatus.objects.get_or_create(pk=1)
    if status.status == 'done' and not force:
        logger.info("Database already seeded. Use force=True to re-seed.")
        return status

    status.status = 'running'
    status.error_message = ''
    status.save()

    funds_data = None
    source_used = "mfapi"

    # --- Primary: mfapi.in ---
    try:
        funds_data = _fetch_funds_from_mfapi()
        logger.info(f"mfapi.in returned {len(funds_data)} fund records")
    except Exception as exc:
        logger.warning(f"mfapi.in seed failed after retries: {exc}. Trying AMFI fallback…")

    # --- Fallback: AMFI NAVAll.txt ---
    if not funds_data:
        try:
            funds_data = _fetch_funds_from_amfi()
            source_used = "amfi"
        except Exception as exc:
            msg = f"Both mfapi.in and AMFI fallback failed: {exc}"
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
        url = f"{MFAPI_BASE}/{fund.scheme_code}"
        raw = _fetch_with_retry(url, max_retries=3, timeout=20)
        data = json.loads(raw)

        meta = data.get('meta', {})
        fund.amc = meta.get('fund_house', fund.amc or '')
        fund.category = meta.get('scheme_category', fund.category or '')
        fund.fund_type = meta.get('scheme_type', fund.fund_type or '')

        nav_data = data.get('data', [])
        if nav_data:
            latest = nav_data[0]
            try:
                nav_val = float(latest['nav'])
                nav_date = datetime.strptime(latest['date'], '%d-%m-%Y').date()
                fund.current_nav = nav_val
                fund.nav_date = nav_date
                fund.nav_last_updated = timezone.now()
                fund.save()
            except (ValueError, KeyError) as e:
                logger.warning(f"Could not parse NAV for {fund.scheme_code}: {e}")

        if fetch_history:
            _save_nav_history(fund, nav_data)

        return fund
    except requests.RequestException as e:
        logger.error(f"Failed to fetch NAV for fund {fund.scheme_code}: {e}")
        raise


def _save_nav_history(fund, nav_data):
    """Bulk save NAV history entries."""
    existing_dates = set(
        NAVHistory.objects.filter(fund=fund).values_list('date', flat=True)
    )
    to_create = []
    for entry in nav_data:
        try:
            d = datetime.strptime(entry['date'], '%d-%m-%Y').date()
            nav = float(entry['nav'])
            if d not in existing_dates:
                to_create.append(NAVHistory(fund=fund, date=d, nav=nav))
        except (ValueError, KeyError):
            continue

    if to_create:
        NAVHistory.objects.bulk_create(to_create, ignore_conflicts=True)
        logger.info(f"Saved {len(to_create)} NAV history entries for {fund.scheme_code}")


def refresh_all_navs():
    """Refresh current NAV for all active funds. Called by scheduler."""
    funds = MutualFund.objects.filter(is_active=True)
    success = errors = 0
    for fund in funds:
        try:
            fetch_fund_nav(fund)
            success += 1
            time.sleep(0.1)  # Rate limit
        except Exception as e:
            errors += 1
            logger.error(f"NAV refresh error for {fund.scheme_code}: {e}")
    logger.info(f"NAV refresh complete: {success} success, {errors} errors.")
    return success, errors


def search_funds(query, limit=20):
    """Search funds by name or scheme code."""
    from django.db.models import Q
    qs = MutualFund.objects.filter(is_active=True)
    if query.isdigit():
        qs = qs.filter(Q(scheme_code=int(query)) | Q(scheme_name__icontains=query))
    else:
        for word in query.split():
            qs = qs.filter(scheme_name__icontains=word)
    return qs[:limit]
