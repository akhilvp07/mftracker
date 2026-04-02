"""
Pluggable factsheet fetcher.

Data sources (all free, no API key required):
─────────────────────────────────────────────
1. mfapi.in  /{scheme_code}
     → fund_house (AMC), scheme_category, scheme_type, NAV history
     → Does NOT provide: fund manager name, holdings, AUM

2. AMFI Portfolio Disclosure (primary holdings source)
     https://www.amfiindia.com/modules/PortfolioDetails?fundId=<scheme_code>
     → Monthly portfolio: stock name, ISIN, sector, % to NAV

3. AMFI Consolidated Portfolio file (fallback holdings source)
     https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx
     → Pipe-delimited, all schemes

4. AMFI NAVAll.txt  (fund manager name source)
     https://www.amfiindia.com/spages/NAVAll.txt  — full nav list with metadata
     Note: NAVAll.txt does NOT contain fund manager names.

5. AMFI Scheme Information Document search
     https://www.amfiindia.com/research-information/other-data/scheme-documents
     → Correct source for fund manager names, but HTML-heavy.

6. Best practical approach for fund manager: 
     Scheme-wise data from BSE MF / NSE MF endpoints (truly free, no auth):
     https://bseindia.com/MutualFund/Scheme_Master.aspx  (downloadable)
     NSE MFI data: https://www.nseindia.com/products/content/equities/mfs/mf_master.htm

Since all live endpoints are blocked in this build environment, the fetcher
is written to be robust and correct when run on the user's machine. 
We use a tiered strategy:
  - mfapi.in for metadata + NAV
  - AMFI PortfolioDetails HTML for holdings (parsed with multiple regex patterns 
    matching different AMFI table layouts)
  - Fund manager extracted from Scheme Information Document summary page
"""

import re
import json
import time
import logging
import requests
from datetime import date
from django.utils import timezone
from django.conf import settings
from funds.models import MutualFund
from .models import (
    Factsheet, FactsheetHolding, SectorAllocation,
    FactsheetFetchLog, FactsheetDiff,
)

logger = logging.getLogger(__name__)

MFAPI_BASE   = "https://api.mfapi.in/mf"
AMFI_PORTAL  = "https://www.amfiindia.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

class FetchError(Exception):
    pass


def _http_get(url, *, retries=3, timeout=20, as_text=False):
    """
    Stream-read with exponential back-off retry.
    Returns bytes (or str if as_text=True). Raises FetchError on failure.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            resp.raise_for_status()
            chunks = []
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
            raw = b"".join(chunks)
            return raw.decode("utf-8", errors="replace") if as_text else raw
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            last_exc = exc
            wait = 2 ** (attempt - 1)
            logger.debug(f"HTTP attempt {attempt} failed for {url}: {exc}. Retry in {wait}s")
            time.sleep(wait)
        except requests.exceptions.HTTPError as exc:
            raise FetchError(f"HTTP {exc.response.status_code} for {url}") from exc

    raise FetchError(f"All {retries} attempts failed for {url}: {last_exc}") from last_exc


def _http_get_json(url, **kw):
    raw = _http_get(url, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"Invalid JSON from {url}: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Source 1 — mfapi.in  (metadata + NAV, no holdings/manager)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_mfapi_meta(scheme_code):
    """
    Returns dict with keys: amc, category, scheme_type.
    Raises FetchError on network failure.
    """
    data = _http_get_json(f"{MFAPI_BASE}/{scheme_code}")
    meta = data.get("meta", {})
    return {
        "amc":          meta.get("fund_house", "").strip(),
        "category":     meta.get("scheme_category", "").strip(),
        "scheme_type":  meta.get("scheme_type", "").strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Source 2 — AMFI Portfolio Disclosure HTML
# https://www.amfiindia.com/modules/PortfolioDetails?fundId=<code>
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_amfi_portfolio_page(scheme_code):
    """
    Fetch AMFI portfolio disclosure HTML for a scheme.
    Returns (fund_manager: str, holdings: list, sectors: dict).
    """
    url = f"{AMFI_PORTAL}/modules/PortfolioDetails?fundId={scheme_code}"
    html = _http_get(url, timeout=20, as_text=True)
    fund_manager = _parse_fund_manager(html)
    holdings, sectors = _parse_holdings_table(html)
    return fund_manager, holdings, sectors


def _parse_fund_manager(html: str) -> str:
    """
    Extract fund manager name(s) from AMFI portfolio page.
    The page contains a line like:
      Fund Manager: Mr. Neelesh Surana / Ms. Harsha Upadhyaya
    or inside a <td> cell.
    """
    patterns = [
        # "Fund Manager : Name" anywhere in the text
        r"Fund\s+Manager\s*[:\-]\s*([A-Za-z\s\./,&]+?)(?:<|\n|$|;|Fund)",
        # <td>Fund Manager</td><td>Name</td>
        r"Fund\s+Manager</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>",
        # Sometimes in a <th> row
        r"Fund\s+Manager\s*</th>\s*<td[^>]*>\s*([^<]+?)\s*</td>",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" ,./\n\t")
            # Filter out noise
            if name and len(name) > 3 and len(name) < 200:
                return name
    return ""


def _parse_holdings_table(html: str):
    """
    Parse holdings table from AMFI portfolio disclosure HTML.

    AMFI uses several table layouts over the years. We try multiple patterns.

    Typical column order: Company Name | ISIN | Rating | Industry | % to NAV
    Older layout:         Company Name | ISIN | Industry | Mkt Value | % to NAV

    Returns:
        holdings: list of {'name', 'isin', 'sector', 'weight'}
        sectors:  dict  sector_name → total_weight
    """
    holdings = []
    sectors  = {}

    # ── Strategy 1: parse <table> with <tr><td> rows ──────────────────────
    # Find all <tr> blocks that contain numeric % values
    # We look for rows with 4-6 <td> cells where the last numeric cell ≤ 100

    tr_pattern = re.compile(
        r"<tr[^>]*>(.*?)</tr>",
        re.DOTALL | re.IGNORECASE,
    )
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    strip_tags = re.compile(r"<[^>]+>")

    for tr_match in tr_pattern.finditer(html):
        row_html = tr_match.group(1)
        cells = [strip_tags.sub("", td.group(1)).strip()
                 for td in td_pattern.finditer(row_html)]

        # Need at least 4 cells
        if len(cells) < 4:
            continue

        # Last cell that looks like a percentage (0.01 – 99.99)
        pct_cell = None
        pct_idx  = -1
        for i in range(len(cells) - 1, -1, -1):
            val = cells[i].replace(",", "").replace("%", "").strip()
            try:
                f = float(val)
                if 0 < f < 100:
                    pct_cell = f
                    pct_idx  = i
                    break
            except ValueError:
                continue

        if pct_cell is None:
            continue

        # First cell = company name
        name = cells[0].strip()

        # Skip header rows and totals
        if not name or any(kw in name.lower() for kw in (
            "company", "instrument", "total", "grand", "net asset",
            "issuer", "name of", "particulars",
        )):
            continue

        # ISIN: 12-char alphanumeric, often in cell 1
        isin = ""
        for c in cells[1:3]:
            c = c.strip()
            if re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", c):
                isin = c
                break

        # Sector: look for Industry/Sector column.
        # It's a non-empty text cell that is NOT an ISIN and NOT a pure number.
        # Walk cells from position 2 up to (but not including) the % cell.
        # Prefer the LAST qualifying cell before the % (often Industry is last before NAV %).
        sector = ""
        for c in reversed(cells[2:pct_idx]):
            c = c.strip()
            if not c or c == "-":
                continue
            # Skip ISINs
            if re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", c):
                continue
            # Skip pure numbers / amounts (market value columns)
            try:
                float(c.replace(",", "").replace("(", "").replace(")", ""))
                continue   # it's a number, skip
            except ValueError:
                pass
            # Skip rating codes (AAA, AA+, etc.) — but allow short sector names like "IT"
            if len(c) <= 1 or re.match(r"^[A-Z]{2,4}[+][\-]?$", c):
                continue
            sector = c
            break

        holdings.append({
            "name":   name,
            "isin":   isin,
            "sector": sector,
            "weight": round(pct_cell, 4),
        })
        if sector:
            sectors[sector] = round(sectors.get(sector, 0.0) + pct_cell, 4)

    # ── Strategy 2: plain-text fallback ────────────────────────────────────
    # Some AMFI pages render data in plain text with pipe or tab delimiters
    if not holdings:
        holdings, sectors = _parse_holdings_text(html)

    # Sort by weight descending
    holdings.sort(key=lambda x: x["weight"], reverse=True)
    return holdings, sectors


def _parse_holdings_text(html: str):
    """
    Fallback: look for lines like
      Reliance Industries Ltd|INE002A01018|Oil Gas & Consumable Fuels|9.87
    or tab-separated equivalents.
    """
    holdings = []
    sectors  = {}

    # Strip all tags first
    text = re.sub(r"<[^>]+>", "\n", html)

    pct_line = re.compile(
        r"([A-Za-z][A-Za-z0-9 &\.\-\(\)\'\/]{3,60})"   # company name
        r"[\t|;,]"
        r"([A-Z]{2}[A-Z0-9]{10}|[-])?"                  # optional ISIN
        r"[\t|;,]?"
        r"([A-Za-z][^|\t\n;,]{3,40})?"                  # optional sector
        r"[\t|;,]"
        r"([\d]+\.[\d]{1,4})",                           # % weight
        re.MULTILINE,
    )
    for m in pct_line.finditer(text):
        name   = m.group(1).strip()
        isin   = (m.group(2) or "").strip()
        sector = (m.group(3) or "").strip()
        try:
            weight = float(m.group(4))
        except ValueError:
            continue
        if weight <= 0 or weight > 100:
            continue
        if any(kw in name.lower() for kw in ("total", "grand", "net asset")):
            continue
        holdings.append({"name": name, "isin": isin if isin != "-" else "",
                         "sector": sector, "weight": round(weight, 4)})
        if sector:
            sectors[sector] = round(sectors.get(sector, 0.0) + weight, 4)

    holdings.sort(key=lambda x: x["weight"], reverse=True)
    return holdings, sectors


# ─────────────────────────────────────────────────────────────────────────────
# Source 3 — AMFI Scheme-wise data file (fund manager fallback)
# https://www.amfiindia.com/spages/NAVAll.txt  doesn't have manager names.
# Better source: AMFI's scheme master CSV published on their data portal.
# URL: https://www.amfiindia.com/modules/NAVhistory (HTML) 
# 
# Practical free source for fund manager: 
# https://api.mfapi.in/mf/  does NOT have it.
#
# The most reliable free source is actually the scheme-level page on AMFI:
# https://www.amfiindia.com/scheme-information?ISIN=<isin>
# OR the PortfolioDetails page which we already parse above.
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_fund_manager_from_amfi_scheme_page(fund):
    """
    Try AMFI scheme search page to find fund manager.
    Falls back gracefully to empty string.
    """
    # Try the scheme performance page which lists manager
    urls_to_try = [
        f"{AMFI_PORTAL}/modules/PortfolioDetails?fundId={fund.scheme_code}",
        f"{AMFI_PORTAL}/scheme-performance?SchemeCode={fund.scheme_code}",
    ]
    for url in urls_to_try:
        try:
            html = _http_get(url, timeout=15, as_text=True)
            manager = _parse_fund_manager(html)
            if manager:
                return manager
        except FetchError:
            continue
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Fetcher classes (pluggable registry)
# ─────────────────────────────────────────────────────────────────────────────

class FactsheetFetcher:
    def fetch(self, fund, month: date) -> dict:
        raise NotImplementedError


class MFAPIFetcher(FactsheetFetcher):
    """
    Primary fetcher:
      - Metadata from mfapi.in (AMC, category, type)
      - Fund manager + holdings from AMFI portfolio disclosure page
    """

    def fetch(self, fund, month: date) -> dict:
        result = {
            "fund_manager": "",
            "amc":          fund.amc or "",
            "category":     fund.category or "",
            "scheme_type":  fund.fund_type or "",
            "objective":    "",
            "aum":          None,
            "expense_ratio": None,
            "holdings":     [],
            "sectors":      [],
            "source":       "mfapi+amfi",
            "errors":       [],
        }

        # 1 ── mfapi metadata
        try:
            meta = _fetch_mfapi_meta(fund.scheme_code)
            result["amc"]         = meta["amc"]   or result["amc"]
            result["category"]    = meta["category"] or result["category"]
            result["scheme_type"] = meta["scheme_type"] or result["scheme_type"]
        except FetchError as exc:
            result["errors"].append(f"mfapi: {exc}")
            logger.warning(f"mfapi meta failed for {fund.scheme_code}: {exc}")

        # 2 ── AMFI portfolio page (fund manager + holdings)
        try:
            fund_manager, holdings, sectors_dict = _fetch_amfi_portfolio_page(fund.scheme_code)
            result["fund_manager"] = fund_manager
            result["holdings"]     = holdings
            result["sectors"]      = [
                {"name": k, "weight": v}
                for k, v in sorted(sectors_dict.items(), key=lambda x: x[1], reverse=True)
            ]
        except FetchError as exc:
            result["errors"].append(f"amfi_portfolio: {exc}")
            logger.warning(f"AMFI portfolio failed for {fund.scheme_code}: {exc}")

        return result


class AMFIFetcher(FactsheetFetcher):
    """Standalone AMFI-only fetcher."""

    def fetch(self, fund, month: date) -> dict:
        result = {
            "fund_manager": "",
            "amc":  fund.amc or "",
            "category": fund.category or "",
            "scheme_type": "",
            "objective": "",
            "aum": None,
            "expense_ratio": None,
            "holdings": [],
            "sectors": [],
            "source": "amfi",
            "errors": [],
        }
        try:
            fund_manager, holdings, sectors_dict = _fetch_amfi_portfolio_page(fund.scheme_code)
            result["fund_manager"] = fund_manager
            result["holdings"]     = holdings
            result["sectors"]      = [
                {"name": k, "weight": v}
                for k, v in sorted(sectors_dict.items(), key=lambda x: x[1], reverse=True)
            ]
        except FetchError as exc:
            result["errors"].append(str(exc))
        return result


_FETCHER_REGISTRY = {
    "mfapi": MFAPIFetcher,
    "amfi":  AMFIFetcher,
}


def get_fetcher(name="mfapi") -> FactsheetFetcher:
    return _FETCHER_REGISTRY.get(name, MFAPIFetcher)()


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def fetch_factsheet_for_fund(fund, month=None, fetcher_name="mfapi"):
    if month is None:
        month = date.today().replace(day=1)

    fetcher = get_fetcher(fetcher_name)
    try:
        data = fetcher.fetch(fund, month)
    except Exception as exc:
        logger.error(f"Fetcher raised for {fund.scheme_code}: {exc}")
        Factsheet.objects.update_or_create(
            fund=fund, month=month,
            defaults={"fetch_error": str(exc)}
        )
        raise

    # Propagate better metadata back onto the MutualFund row
    fund_dirty = []
    if data.get("amc") and not fund.amc:
        fund.amc = data["amc"]; fund_dirty.append("amc")
    if data.get("category") and not fund.category:
        fund.category = data["category"]; fund_dirty.append("category")
    if data.get("scheme_type") and not fund.fund_type:
        fund.fund_type = data["scheme_type"]; fund_dirty.append("fund_type")
    if fund_dirty:
        fund.save(update_fields=fund_dirty)

    # Build fetch_error summary (non-fatal partial errors)
    error_summary = "; ".join(data.get("errors", []))

    factsheet, _ = Factsheet.objects.update_or_create(
        fund=fund,
        month=month,
        defaults={
            "fund_manager":  data.get("fund_manager", ""),
            "category":      data.get("category") or fund.category or "",
            "objective":     data.get("objective", ""),
            "aum":           data.get("aum"),
            "expense_ratio": data.get("expense_ratio"),
            "fetch_error":   error_summary,
        },
    )

    if data.get("holdings"):
        FactsheetHolding.objects.filter(factsheet=factsheet).delete()
        FactsheetHolding.objects.bulk_create([
            FactsheetHolding(
                factsheet=factsheet,
                stock_name=h["name"],
                isin=h.get("isin", ""),
                weight=h["weight"],
                sector=h.get("sector", ""),
            )
            for h in data["holdings"]
        ])

    if data.get("sectors"):
        SectorAllocation.objects.filter(factsheet=factsheet).delete()
        SectorAllocation.objects.bulk_create([
            SectorAllocation(factsheet=factsheet, sector_name=s["name"], weight=s["weight"])
            for s in data["sectors"]
        ])

    _generate_diff(fund, factsheet)
    return factsheet


# ─────────────────────────────────────────────────────────────────────────────
# Diff engine
# ─────────────────────────────────────────────────────────────────────────────

def _generate_diff(fund, current_factsheet):
    from dateutil.relativedelta import relativedelta
    prev_month = current_factsheet.month - relativedelta(months=1)
    try:
        prev = Factsheet.objects.get(fund=fund, month=prev_month)
    except Factsheet.DoesNotExist:
        return

    threshold = float(getattr(settings, "WEIGHT_CHANGE_THRESHOLD", 1.0))

    curr_h = {h.stock_name: float(h.weight) for h in current_factsheet.holdings.all()}
    prev_h = {h.stock_name: float(h.weight) for h in prev.holdings.all()}

    new_holdings    = [{"name": n, "weight": curr_h[n]} for n in curr_h if n not in prev_h]
    exited_holdings = [{"name": n, "weight": prev_h[n]} for n in prev_h if n not in curr_h]
    weight_changes  = []
    for name in set(curr_h) & set(prev_h):
        delta = curr_h[name] - prev_h[name]
        if abs(delta) >= threshold:
            weight_changes.append({
                "name": name, "prev": prev_h[name],
                "curr": curr_h[name], "delta": round(delta, 4),
            })
    weight_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

    curr_s = {s.sector_name: float(s.weight) for s in current_factsheet.sectors.all()}
    prev_s = {s.sector_name: float(s.weight) for s in prev.sectors.all()}
    sector_changes = []
    for name in set(list(curr_s) + list(prev_s)):
        delta = curr_s.get(name, 0) - prev_s.get(name, 0)
        if abs(delta) >= threshold:
            sector_changes.append({
                "name": name, "prev": prev_s.get(name, 0),
                "curr": curr_s.get(name, 0), "delta": round(delta, 4),
            })

    FactsheetDiff.objects.update_or_create(
        fund=fund, current_month=current_factsheet,
        defaults={
            "previous_month":    prev,
            "new_holdings":      new_holdings,
            "exited_holdings":   exited_holdings,
            "weight_changes":    weight_changes,
            "sector_changes":    sector_changes,
            "manager_changed":   bool(current_factsheet.fund_manager and
                                      current_factsheet.fund_manager != prev.fund_manager),
            "category_changed":  bool(current_factsheet.category and
                                      current_factsheet.category != prev.category),
            "objective_changed": bool(current_factsheet.objective and prev.objective and
                                      current_factsheet.objective != prev.objective),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bulk refresh
# ─────────────────────────────────────────────────────────────────────────────

def run_monthly_factsheet_refresh(user=None):
    log = FactsheetFetchLog.objects.create()
    month = date.today().replace(day=1)

    qs = MutualFund.objects.filter(portfolio_entries__isnull=False)
    if user:
        qs = MutualFund.objects.filter(portfolio_entries__portfolio__user=user)
    funds = qs.distinct()

    errors = processed = 0
    for fund in funds:
        try:
            factsheet = fetch_factsheet_for_fund(fund, month)
            processed += 1
            time.sleep(0.3)
            try:
                diff = FactsheetDiff.objects.get(fund=fund, current_month=factsheet)
                _create_diff_alerts(fund, diff, user)
            except FactsheetDiff.DoesNotExist:
                pass
        except Exception as exc:
            errors += 1
            log.error_detail += f"\n{fund.scheme_code}: {exc}"

    log.status          = "done" if errors == 0 else "partial"
    log.funds_processed = processed
    log.errors          = errors
    log.finished_at     = timezone.now()
    log.save()
    return log


def _create_diff_alerts(fund, diff, user=None):
    from alerts.services import create_alert
    from django.contrib.auth.models import User

    uid_qs = (MutualFund.objects
              .filter(pk=fund.pk)
              .values_list("portfolio_entries__portfolio__user", flat=True)
              .distinct())

    for uid in uid_qs:
        if uid is None:
            continue
        if user and getattr(user, "pk", None) != uid:
            continue
        try:
            u = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue

        if diff.manager_changed:
            create_alert(u, fund, "fund_manager_change", "critical",
                f"Fund manager changed: {fund.scheme_name}",
                f"The fund manager for {fund.scheme_name} has changed.")
        if diff.category_changed:
            create_alert(u, fund, "category_change", "warning",
                f"Category changed: {fund.scheme_name}",
                f"Fund category has changed for {fund.scheme_name}.")
        for h in diff.new_holdings[:3]:
            create_alert(u, fund, "new_holding", "info",
                f"New holding in {fund.scheme_name}",
                f'{h["name"]} added ({h["weight"]:.2f}%)')
        for h in diff.exited_holdings[:3]:
            create_alert(u, fund, "holding_exit", "info",
                f"Holding exited in {fund.scheme_name}",
                f'{h["name"]} fully exited')

