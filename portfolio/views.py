import logging
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Portfolio, PortfolioFund, PurchaseLot, XIRRCache
from funds.models import MutualFund
from .xirr import calculate_fund_xirr, calculate_portfolio_xirr
from funds.services import fetch_fund_nav
from django.conf import settings

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user)
    holdings = portfolio.holdings.select_related('fund').prefetch_related('lots').all()

    from funds.models import SeedStatus
    seed_status = SeedStatus.objects.filter(pk=1).first()

    holdings_data = []
    total_invested = Decimal('0')
    total_current = Decimal('0')

    for pf in holdings:
        invested = pf.total_invested
        current = pf.current_value
        gain = current - invested
        gain_pct = (gain / invested * 100) if invested > 0 else Decimal('0')

        # Get cached XIRR
        xirr_obj = XIRRCache.objects.filter(portfolio_fund=pf).first()
        xirr_val = float(xirr_obj.xirr_value) * 100 if xirr_obj and xirr_obj.xirr_value else None

        holdings_data.append({
            'pf': pf,
            'invested': invested,
            'current': current,
            'gain': gain,
            'gain_pct': gain_pct,
            'xirr': xirr_val,
        })
        total_invested += invested
        total_current += current

    total_gain = total_current - total_invested
    total_gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else Decimal('0')

    portfolio_xirr_obj = XIRRCache.objects.filter(portfolio=portfolio, portfolio_fund=None).first()
    portfolio_xirr = float(portfolio_xirr_obj.xirr_value) * 100 if portfolio_xirr_obj and portfolio_xirr_obj.xirr_value else None

    return render(request, 'portfolio/dashboard.html', {
        'portfolio': portfolio,
        'holdings_data': holdings_data,
        'total_invested': total_invested,
        'total_current': total_current,
        'total_gain': total_gain,
        'total_gain_pct': total_gain_pct,
        'portfolio_xirr': portfolio_xirr,
        'seed_status': seed_status,
    })


@login_required
def fund_detail(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    lots = pf.lots.all()

    # Fetch NAV history for chart
    from funds.models import NAVHistory
    nav_history = NAVHistory.objects.filter(fund=pf.fund).order_by('date')[:365]

    # Get factsheet diff
    from factsheets.models import FactsheetDiff, Factsheet
    latest_factsheet = Factsheet.objects.filter(fund=pf.fund).first()
    latest_diff = FactsheetDiff.objects.filter(fund=pf.fund).first()

    # Calculate XIRR
    xirr_val = None
    try:
        rate = calculate_fund_xirr(pf)
        xirr_val = round(rate * 100, 2) if rate is not None else None
    except Exception as e:
        logger.error(f"XIRR calculation error: {e}")

    nav_dates = [str(n.date) for n in nav_history]
    nav_values = [float(n.nav) for n in nav_history]

    return render(request, 'portfolio/fund_detail.html', {
        'pf': pf,
        'lots': lots,
        'nav_dates': nav_dates,
        'nav_values': nav_values,
        'xirr': xirr_val,
        'latest_factsheet': latest_factsheet,
        'latest_diff': latest_diff,
    })


@login_required
def add_fund(request):
    if request.method == 'POST':
        fund_id = request.POST.get('fund_id')
        fund = get_object_or_404(MutualFund, pk=fund_id)
        portfolio, _ = Portfolio.objects.get_or_create(user=request.user)

        pf, created = PortfolioFund.objects.get_or_create(portfolio=portfolio, fund=fund)
        if created:
            # Auto-fetch NAV + history when fund is first added
            try:
                fetch_fund_nav(fund, fetch_history=True)
                messages.success(request, f'Added {fund.scheme_name} to your portfolio. NAV fetched.')
            except Exception as e:
                logger.warning(f"NAV fetch failed on add for {fund.scheme_code}: {e}")
                messages.success(request, f'Added {fund.scheme_name}. NAV will refresh on next scheduled run.')
        else:
            messages.info(request, f'{fund.scheme_name} is already in your portfolio.')

        return redirect('add_lot', pf_id=pf.pk)

    # GET: show search
    query = request.GET.get('q', '')
    results = []
    if query:
        from funds.services import search_funds
        results = search_funds(query)

    return render(request, 'portfolio/add_fund.html', {'query': query, 'results': results})


@login_required
def add_lot(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)

    if request.method == 'POST':
        try:
            units = Decimal(request.POST['units'])
            avg_nav = Decimal(request.POST['avg_nav'])
            purchase_date = request.POST['purchase_date']
            notes = request.POST.get('notes', '')

            if units <= 0 or avg_nav <= 0:
                messages.error(request, 'Units and NAV must be positive.')
            else:
                PurchaseLot.objects.create(
                    portfolio_fund=pf,
                    units=units,
                    avg_nav=avg_nav,
                    purchase_date=purchase_date,
                    notes=notes,
                )
                messages.success(request, f'Lot added: {units} units @ ₹{avg_nav}')
                # Recalculate XIRR
                try:
                    calculate_fund_xirr(pf)
                    calculate_portfolio_xirr(portfolio)
                except Exception as e:
                    logger.warning(f"XIRR recalc error: {e}")
                return redirect('fund_detail', pf_id=pf.pk)
        except (ValueError, KeyError) as e:
            messages.error(request, f'Invalid input: {e}')

    return render(request, 'portfolio/add_lot.html', {'pf': pf})


@login_required
@require_POST
def delete_lot(request, lot_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    lot = get_object_or_404(PurchaseLot, pk=lot_id, portfolio_fund__portfolio=portfolio)
    pf = lot.portfolio_fund
    lot.delete()
    messages.success(request, 'Lot deleted.')
    try:
        calculate_fund_xirr(pf)
        calculate_portfolio_xirr(portfolio)
    except Exception:
        pass
    return redirect('fund_detail', pf_id=pf.pk)


@login_required
@require_POST
def remove_fund(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    name = pf.fund.scheme_name
    pf.delete()
    messages.success(request, f'Removed {name} from portfolio.')
    return redirect('dashboard')


@login_required
@require_POST
def refresh_nav(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    try:
        fetch_fund_nav(pf.fund, fetch_history=True)
        calculate_fund_xirr(pf)
        messages.success(request, 'NAV refreshed successfully.')
    except Exception as e:
        messages.error(request, f'NAV refresh failed: {e}')
    return redirect('fund_detail', pf_id=pf.pk)


@login_required
@require_POST
def recalculate_xirr(request):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    count = 0
    for pf in portfolio.holdings.prefetch_related('lots', 'fund'):
        try:
            calculate_fund_xirr(pf)
            count += 1
        except Exception as e:
            logger.error(f"XIRR error for {pf.pk}: {e}")
    try:
        calculate_portfolio_xirr(portfolio)
    except Exception as e:
        logger.error(f"Portfolio XIRR error: {e}")

    messages.success(request, f'XIRR recalculated for {count} funds.')
    return redirect('dashboard')


@login_required
def settings_view(request):
    from django.conf import settings as django_settings
    kite_connected = bool(
        Portfolio.objects.filter(user=request.user, kite_access_token__gt='').first()
    )
    smtp_configured = bool(django_settings.EMAIL_HOST_USER)

    if request.method == 'POST' and 'seed_db' in request.POST:
        from funds.services import seed_fund_database
        try:
            seed_fund_database(force=True)
            messages.success(request, 'Fund database re-seeded successfully.')
        except Exception as e:
            messages.error(request, f'Seeding failed: {e}')
        return redirect('settings')

    if request.method == 'POST' and 'refresh_factsheets' in request.POST:
        from factsheets.fetcher import run_monthly_factsheet_refresh
        try:
            log = run_monthly_factsheet_refresh(user=request.user)
            messages.success(request, f'Factsheet refresh done: {log.funds_processed} processed, {log.errors} errors.')
        except Exception as e:
            messages.error(request, f'Factsheet refresh failed: {e}')
        return redirect('settings')

    from factsheets.models import FactsheetFetchLog
    recent_logs = FactsheetFetchLog.objects.order_by('-started_at')[:5]

    return render(request, 'portfolio/settings.html', {
        'kite_connected': kite_connected,
        'kite_api_key': django_settings.KITE_API_KEY,
        'smtp_configured': smtp_configured,
        'recent_logs': recent_logs,
        'weight_threshold': django_settings.WEIGHT_CHANGE_THRESHOLD,
    })


@login_required
def api_fund_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    from funds.services import search_funds
    results = search_funds(q, limit=20)
    data = [
        {
            'id': f.pk,
            'text': f.scheme_name,
            'code': f.scheme_code,
            'amc': f.amc or '',
            'nav': str(f.current_nav) if f.current_nav else '',
        }
        for f in results
    ]
    return JsonResponse({'results': data})

