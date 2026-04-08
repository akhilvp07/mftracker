import time
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from .api_cron import cron_refresh_nav
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Q, F
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import date, datetime
import logging
import hashlib

from .models import Portfolio, PortfolioFund, PurchaseLot, XIRRCache
from funds.models import MutualFund, NAVHistory
from factsheets.models import Factsheet, FactsheetDiff
from .xirr import calculate_portfolio_xirr, calculate_fund_xirr
from .services.rebalance import generate_rebalance_suggestion, get_rebalance_summary
from funds.services import search_funds, fetch_fund_nav, seed_fund_database
from .kite_integration import KITE_API_KEY, KITE_API_SECRET

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
        'now': timezone.now(),
    })


@login_required
def fund_detail(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    lots = pf.lots.all()
    
    # Refresh fund data to get latest NAV
    pf.fund.refresh_from_db()

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
            # Mark fund as active since it's now in a portfolio
            fund.is_active = True
            fund.save(update_fields=['is_active'])
            
            # Fetch detailed fund information
            try:
                from funds.services import fetch_fund_details
                details = fetch_fund_details(fund.scheme_code)
                if details:
                    logger.info(f"Fetched detailed info for {fund.scheme_name}")
            except Exception as e:
                logger.warning(f"Failed to fetch fund details: {e}")
            
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
def edit_fund(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    
    if request.method == 'POST':
        # Check if delete action is requested
        if 'delete_fund' in request.POST:
            # Delete all lots first
            pf.lots.all().delete()
            # Delete the portfolio fund
            pf.delete()
            messages.success(request, f'{pf.fund.scheme_name} has been removed from your portfolio.')
            return redirect('dashboard')
        
        # Handle adding new lot
        elif 'add_lot' in request.POST:
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
                        notes=notes
                    )
                    messages.success(request, 'Purchase lot added successfully.')
                    return redirect('edit_fund', pf_id=pf.pk)
            except (ValueError, ValidationError) as e:
                messages.error(request, f'Invalid input: {e}')
        
        # Handle editing existing lot
        elif 'edit_lot' in request.POST:
            lot_id = request.POST.get('lot_id')
            lot = get_object_or_404(PurchaseLot, pk=lot_id, portfolio_fund=pf)
            try:
                lot.units = Decimal(request.POST['units'])
                lot.avg_nav = Decimal(request.POST['avg_nav'])
                lot.purchase_date = request.POST['purchase_date']
                lot.notes = request.POST.get('notes', '')
                lot.save()
                messages.success(request, 'Purchase lot updated successfully.')
            except (ValueError, ValidationError) as e:
                messages.error(request, f'Invalid input: {e}')
        
        # Handle deleting a lot
        elif 'delete_lot' in request.POST:
            lot_id = request.POST.get('lot_id')
            lot = get_object_or_404(PurchaseLot, pk=lot_id, portfolio_fund=pf)
            lot.delete()
            messages.success(request, 'Purchase lot deleted successfully.')

    # Get all lots for this fund
    lots = pf.lots.all().order_by('purchase_date')
    
    return render(request, 'portfolio/edit_fund.html', {
        'pf': pf,
        'lots': lots,
    })


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
        # Always fetch history when manually refreshing individual fund
        fetch_fund_nav(pf.fund, fetch_history=True)
        calculate_fund_xirr(pf)
        
        # Check if NAV history was fetched
        from funds.models import NAVHistory
        history_count = NAVHistory.objects.filter(fund=pf.fund).count()
        logger.info(f"NAV history count for {pf.fund.scheme_code}: {history_count}")
        
        # Reload the fund object to get updated data
        pf.fund.refresh_from_db()
        
        messages.success(request, f'NAV refreshed successfully. History entries: {history_count}')
    except Exception as e:
        logger.error(f"NAV refresh error for {pf.fund.scheme_code}: {e}")
        messages.error(request, f'NAV refresh failed: {e}')
    return redirect('fund_detail', pf_id=pf.pk)


@login_required
@require_POST
def refresh_all_nav(request):
    """Refresh NAV for all funds in the user's portfolio"""
    logger.info(f"Starting bulk NAV refresh for user {request.user.username}")
    
    portfolio = get_object_or_404(Portfolio, user=request.user)
    holdings = portfolio.holdings.select_related('fund').all()
    
    logger.info(f"Found {len(holdings)} funds in portfolio")
    
    if not holdings:
        messages.info(request, 'No funds in portfolio to refresh.')
        return redirect('dashboard')
    
    success_count = 0
    error_count = 0
    
    # Refresh each fund sequentially to avoid threading issues
    for i, holding in enumerate(holdings):
        logger.info(f"Processing fund {i+1}/{len(holdings)}: {holding.fund.scheme_name}")
        try:
            # Use optimized /latest endpoint for faster refresh
            fetch_fund_nav(holding.fund, fetch_history=False)
            calculate_fund_xirr(holding)
            success_count += 1
            logger.info(f"Successfully refreshed NAV for {holding.fund.scheme_name}")
        except Exception as e:
            error_count += 1
            logger.error(f"Failed to refresh NAV for {holding.fund.scheme_name}: {e}")
    
    # Recalculate portfolio XIRR after all NAVs are updated
    try:
        calculate_portfolio_xirr(portfolio)
    except Exception as e:
        logger.error(f"Failed to recalculate portfolio XIRR: {e}")
    
    # Show result message
    logger.info(f"Bulk NAV refresh completed: {success_count} success, {error_count} errors")
    if error_count == 0:
        messages.success(request, f'Successfully refreshed NAV for all {success_count} funds!')
    elif success_count > 0:
        messages.warning(request, f'Refreshed {success_count} funds, {error_count} failed. Check logs for details.')
    else:
        messages.error(request, f'Failed to refresh any NAV. Please try again later.')
    
    return redirect('dashboard')


@login_required
def test_refresh(request):
    """Test view to debug button submission"""
    logger.info("TEST: test_refresh view accessed")
    messages.info(request, "Test refresh successful!")
    return redirect('dashboard')


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
    from .models import AssetAllocation
    from .services.rebalance import calculate_current_allocation
    
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user)
    kite_connected = bool(portfolio.kite_access_token)
    smtp_configured = bool(django_settings.EMAIL_HOST_USER)
    
    # Get or create asset allocation
    asset_allocation, created = AssetAllocation.objects.get_or_create(portfolio=portfolio)
    
    # Calculate current allocation
    current_allocation, total_value = calculate_current_allocation(portfolio)
    
    # Convert Decimal values to float for template
    current_allocation_float = {k: float(v) for k, v in current_allocation.items()}

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
    
    # Handle asset allocation form submission
    if request.method == 'POST' and 'save_allocation' in request.POST:
        try:
            # Update asset allocation
            asset_allocation.equity_percentage = Decimal(request.POST.get('equity_percentage', 60))
            asset_allocation.debt_percentage = Decimal(request.POST.get('debt_percentage', 30))
            asset_allocation.gold_percentage = Decimal(request.POST.get('gold_percentage', 10))
            asset_allocation.large_cap_percentage = Decimal(request.POST.get('large_cap_percentage', 50))
            asset_allocation.mid_cap_percentage = Decimal(request.POST.get('mid_cap_percentage', 30))
            asset_allocation.small_cap_percentage = Decimal(request.POST.get('small_cap_percentage', 20))
            asset_allocation.rebalance_threshold = Decimal(request.POST.get('rebalance_threshold', 5))
            
            asset_allocation.full_clean()
            asset_allocation.save()
            messages.success(request, 'Asset allocation settings saved successfully.')
        except ValidationError as e:
            messages.error(request, f'Error: {e}')
        except (ValueError, KeyError):
            messages.error(request, 'Invalid input values.')
        return redirect('settings')

    from factsheets.models import FactsheetFetchLog
    recent_logs = FactsheetFetchLog.objects.order_by('-started_at')[:5]

    # Get Kite credentials from settings
    kite_api_key = django_settings.KITE_API_KEY

    return render(request, 'portfolio/settings.html', {
        'portfolio': portfolio,
        'kite_connected': kite_connected,
        'kite_api_key': kite_api_key,
        'smtp_configured': smtp_configured,
        'recent_logs': recent_logs,
        'weight_threshold': django_settings.WEIGHT_CHANGE_THRESHOLD,
        'asset_allocation': asset_allocation,
        'current_allocation': current_allocation_float,
        'total_value': total_value,
    })


@login_required
def api_rebalance_progress(request):
    """API endpoint to check rebalancing progress"""
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({'error': 'No task ID provided'}, status=400)
    
    from django.core.cache import cache
    
    # Check for error
    error = cache.get(f"task_{task_id}_error")
    if error:
        return JsonResponse({'error': error, 'status': 'error'})
    
    # Check progress
    progress = cache.get(f"task_{task_id}_progress", 0)
    result = cache.get(f"task_{task_id}_result")
    
    response = {
        'progress': progress,
        'status': 'completed' if progress == 100 else 'running'
    }
    
    if result:
        response['result'] = result
    
    return JsonResponse(response)


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
            'isin': f.isin or '',
        }
        for f in results
    ]
    return JsonResponse({'results': data})


@login_required
def rebalance_view(request):
    from .models import AssetAllocation, RebalanceSuggestion
    from .services.rebalance import generate_rebalance_suggestion, get_rebalance_summary, calculate_current_allocation
    
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user)
    
    # Get current allocation
    current_allocation, total_value = calculate_current_allocation(portfolio)
    
    # Convert Decimal values to float for template
    current_allocation_float = {k: float(v) for k, v in current_allocation.items()}
    
    # Get latest suggestion or generate new one
    latest_suggestion = RebalanceSuggestion.objects.filter(portfolio=portfolio).first()
    
    if request.method == 'POST' and 'generate_suggestion' in request.POST:
        try:
            # Check if this is an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                # Generate new suggestion
                from .tasks import generate_rebalance_suggestion_task
                # Run the task synchronously for now, but with progress tracking
                task_id = f"rebalance_{request.user.id}_{int(time.time())}"
                
                # Start the task in background (for now, run synchronously)
                # In production, you might want to use Celery for true async processing
                import threading
                def run_task():
                    generate_rebalance_suggestion_task(task_id, portfolio.id)
                
                thread = threading.Thread(target=run_task)
                thread.start()
                
                return JsonResponse({'redirect': True, 'task_id': task_id})
            else:
                # Normal form submission
                suggestion = generate_rebalance_suggestion(portfolio)
                if suggestion:
                    messages.success(request, 'Rebalancing suggestion generated successfully.')
                    latest_suggestion = suggestion
                else:
                    messages.info(request, 'Portfolio is already balanced within the threshold. No rebalancing needed.')
                return redirect('rebalance')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': str(e)}, status=500)
            else:
                messages.error(request, f'Failed to generate suggestion: {e}')
                return redirect('rebalance')
    
    if request.method == 'POST' and 'mark_applied' in request.POST and latest_suggestion:
        latest_suggestion.is_applied = True
        latest_suggestion.save()
        messages.success(request, 'Rebalancing marked as applied.')
        return redirect('rebalance')
    
    # Get summary if suggestion exists
    suggestion_summary = None
    if latest_suggestion:
        suggestion_summary = get_rebalance_summary(latest_suggestion)
    
    # Get asset allocation for display
    asset_allocation, _ = AssetAllocation.objects.get_or_create(portfolio=portfolio)
    
    # Get all portfolio funds with their details
    portfolio_funds = portfolio.holdings.select_related('fund').order_by('fund__scheme_name')
    
    return render(request, 'portfolio/rebalance.html', {
        'portfolio': portfolio,
        'current_allocation': current_allocation_float,
        'total_value': total_value,
        'asset_allocation': asset_allocation,
        'latest_suggestion': latest_suggestion,
        'suggestion_summary': suggestion_summary,
        'portfolio_funds': portfolio_funds,
    })


@login_required
def kite_login(request):
    """Redirect user to Kite for authentication"""
    from .kite_integration import initiate_kite_login
    return initiate_kite_login(request)


@login_required
def kite_callback(request):
    """Handle callback from Kite after authentication"""
    from .kite_integration import kite_callback as handle_callback
    return handle_callback(request)


def kite_postback(request):
    """Handle postbacks from Kite (order updates, etc.)"""
    from .kite_integration import kite_postback as handle_postback
    return handle_postback(request)


@login_required
def sync_kite_holdings(request):
    """Manually sync holdings from Kite"""
    from .kite_integration import fetch_and_sync_holdings, get_kite_session
    
    if not get_kite_session(request):
        messages.error(request, 'Please connect your Kite account first.')
        return redirect('dashboard')
    
    try:
        fetch_and_sync_holdings(request)
        messages.success(request, 'Your mutual fund holdings have been synced from Kite!')
    except Exception as e:
        logger.error(f"Error syncing Kite holdings: {e}")
        messages.error(request, f'Error syncing holdings: {str(e)}')
    
    return redirect('dashboard')

