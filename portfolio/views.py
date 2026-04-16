import time
import json
import re
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from django.core.management import call_command
from .api_cron import cron_refresh_nav
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Q, F
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import date, datetime
import logging
import hashlib

from .models import Portfolio, PortfolioFund, PurchaseLot, XIRRCache, CASImport, CASTransaction
from funds.models import MutualFund, NAVHistory
from factsheets.models import Factsheet, FactsheetDiff
from .xirr import calculate_portfolio_xirr, calculate_fund_xirr
from .services.rebalance import generate_rebalance_suggestion, get_rebalance_summary
from funds.services import search_funds, fetch_fund_nav, seed_fund_database
from .casparser_service import cas_parser_service

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user)
    holdings = portfolio.holdings.select_related('fund').prefetch_related('lots').all()

    from funds.models import SeedStatus
    seed_status = SeedStatus.objects.filter(pk=1).first()

    # Auto-refresh NAV for funds that need it (check intelligently)
    from .utils import bulk_check_and_refresh
    import time
    from datetime import datetime
    
    last_check = request.session.get('last_nav_auto_check', 0)
    current_time = int(time.time())
    current_hour = datetime.now().hour
    
    # Only check if:
    # 1. Last check was more than 2 hours ago (reduced frequency)
    # 2. It's between 7 PM - 11 PM on weekdays (when NAV updates happen)
    if (current_time - last_check > 7200 and  # 2 hours = 7200 seconds
        current_hour >= 19 and current_hour <= 23 and  # 7 PM to 11 PM
        datetime.now().weekday() < 5):  # Monday to Friday
        bulk_check_and_refresh(request, portfolio, fetch_history=False)
        request.session['last_nav_auto_check'] = current_time

    # Get sorting parameters
    sort_by = request.GET.get('sort', 'fund_name')
    sort_order = request.GET.get('order', 'asc')
    
    # Build holdings data
    holdings_data = []
    for pf in holdings:
        # Calculate invested amount as effective cost of current holdings
        # This includes all purchases and redemptions
        invested = pf.total_invested  # This already includes all lots (positive and negative)
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
            'nav': pf.fund.current_nav or Decimal('0'),
            'day_change_pct': pf.fund.day_change_pct or Decimal('0'),
            'total_units': pf.total_units,
        })

    # Sort holdings data
    sort_key_map = {
        'fund_name': lambda x: x['pf'].fund.scheme_name.lower(),
        'nav': lambda x: x['nav'],
        'day_change': lambda x: x['day_change_pct'],
        'units': lambda x: x['total_units'],
        'invested': lambda x: x['invested'],
        'current': lambda x: x['current'],
        'gain_pct': lambda x: x['gain_pct'],
        'xirr': lambda x: x['xirr'] or Decimal('-999'),
    }
    
    if sort_by in sort_key_map:
        reverse = sort_order == 'desc'
        holdings_data.sort(key=sort_key_map[sort_by], reverse=reverse)
    
    # Calculate totals
    total_invested = sum(item['invested'] for item in holdings_data)
    total_current = sum(item['current'] for item in holdings_data)

    total_gain = total_current - total_invested
    total_gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else Decimal('0')

    portfolio_xirr_obj = XIRRCache.objects.filter(portfolio=portfolio, portfolio_fund=None).first()
    portfolio_xirr = None
    
    # Calculate fresh XIRR if cache is old (>24 hours) or doesn't exist
    from datetime import timedelta
    cache_age_threshold = timezone.now() - timedelta(hours=24)
    
    if not portfolio_xirr_obj or portfolio_xirr_obj.calculated_at < cache_age_threshold:
        logger.info(f"XIRR cache is old or missing, calculating fresh XIRR for portfolio {portfolio.name}")
        try:
            from .xirr import calculate_portfolio_xirr
            portfolio_xirr_value = calculate_portfolio_xirr(portfolio)
            portfolio_xirr = float(portfolio_xirr_value) * 100 if portfolio_xirr_value is not None else None
            logger.info(f"Fresh portfolio XIRR calculated: {portfolio_xirr:.2f}%")
        except Exception as e:
            logger.error(f"Failed to calculate fresh portfolio XIRR: {e}")
            # Fall back to cached value if available
            portfolio_xirr = float(portfolio_xirr_obj.xirr_value) * 100 if portfolio_xirr_obj and portfolio_xirr_obj.xirr_value else None
    else:
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
        'current_sort': sort_by,
        'current_order': sort_order,
    })


@login_required
def fund_detail(request, pf_id):
    portfolio = get_object_or_404(Portfolio, user=request.user)
    pf = get_object_or_404(PortfolioFund, pk=pf_id, portfolio=portfolio)
    lots = pf.lots.all()
    
    # Refresh fund data to get latest NAV
    pf.fund.refresh_from_db()
    
    # Get period from request (default: 1y)
    period = request.GET.get('period', '1y')
    
    # Auto-refresh NAV if needed
    from .utils import auto_refresh_if_needed
    import time
    from datetime import timedelta
    
    # Check for session-based auto-refresh flag (from middleware)
    auto_refresh_info = request.session.pop('auto_refresh_nav', None)
    if auto_refresh_info and str(auto_refresh_info['fund_id']) == str(pf.fund.pk):
        # Force refresh regardless of checks
        try:
            from funds.services import fetch_fund_nav
            fetch_fund_nav(pf.fund, fetch_history=True)
            pf.fund.refresh_from_db()
            messages.info(request, f"Auto-refreshed NAV: {auto_refresh_info['reason']}")
            logger.info(f"Force auto-refreshed NAV for {pf.fund.scheme_code}")
        except Exception as e:
            logger.warning(f"Force auto-refresh failed for {pf.fund.scheme_code}: {e}")
    else:
        # Check per-fund cache to avoid too frequent refreshes
        fund_cache_key = f'nav_check_{pf.fund.pk}'
        last_check = request.session.get(fund_cache_key, 0)
        current_time = int(time.time())
        
        # Only check if last check was more than 30 minutes ago
        # And only fetch history if the chart needs it (check if we have enough history)
        if current_time - last_check > 1800:  # 30 minutes = 1800 seconds
            # Check if we have enough history for the selected period
            from funds.models import NAVHistory
            history_needed = {
                '1y': 365,
                '3y': 1095,
                '5y': 1825,
                'all': 0  # All available
            }
            
            days_needed = history_needed.get(period, 365)
            if days_needed > 0:
                oldest_date = timezone.now().date() - timedelta(days=days_needed)
                history_count = NAVHistory.objects.filter(
                    fund=pf.fund, 
                    date__gte=oldest_date
                ).count()
                
                # Only fetch history if we have less than 80% of needed data
                fetch_history = history_count < (days_needed * 0.8)
            else:
                fetch_history = False  # 'all' period doesn't need refresh
            
            auto_refresh_if_needed(request, pf.fund, fetch_history=fetch_history)
            request.session[fund_cache_key] = current_time
    
    # Fetch NAV history for chart
    from funds.models import NAVHistory
    from datetime import datetime, timedelta
    
    # Get all history ordered by date
    all_history = NAVHistory.objects.filter(fund=pf.fund).order_by('date')
    
    # Calculate available periods based on data
    oldest_date = all_history.first().date if all_history.exists() else None
    newest_date = all_history.last().date if all_history.exists() else None
    
    available_periods = []
    if oldest_date:
        days_available = (newest_date - oldest_date).days
        
        # Check which periods are available
        if days_available >= 365:
            available_periods.append('1y')
        if days_available >= 1095:  # 3 years
            available_periods.append('3y')
        if days_available >= 1825:  # 5 years
            available_periods.append('5y')
        available_periods.append('all')
    
    # Filter history based on selected period
    if period == '1y' and oldest_date:
        cutoff_date = newest_date - timedelta(days=365)
        nav_history = all_history.filter(date__gte=cutoff_date)
    elif period == '3y' and oldest_date:
        cutoff_date = newest_date - timedelta(days=1095)
        nav_history = all_history.filter(date__gte=cutoff_date)
    elif period == '5y' and oldest_date:
        cutoff_date = newest_date - timedelta(days=1825)
        nav_history = all_history.filter(date__gte=cutoff_date)
    else:  # 'all' or any other value
        nav_history = all_history

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
        'period': period,
        'available_periods': available_periods,
        'oldest_date': oldest_date,
        'newest_date': newest_date,
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
                from funds.services import fetch_fund_nav
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
    
    # Auto-refresh NAV if needed
    from .utils import auto_refresh_if_needed
    auto_refresh_if_needed(request, pf.fund)
    
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
    
    # Auto-refresh NAV if needed
    from .utils import auto_refresh_if_needed
    auto_refresh_if_needed(request, pf.fund)

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
    
    # Clear auto-refresh cache for this fund
    request.session.pop(f'nav_check_{pf.fund.pk}', None)
    
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
    """Refresh NAV for all funds in user's portfolio using bulk API."""
    # Clear auto-refresh cache when manually refreshing
    request.session.pop('last_nav_auto_check', None)
    
    from funds.services import refresh_all_nav_bulk
    
    logger.info(f"User {request.user.username} requested bulk NAV refresh")
    
    # Get user's portfolio
    try:
        portfolio = Portfolio.objects.get(user=request.user)
    except Portfolio.DoesNotExist:
        messages.error(request, 'No portfolio found.')
        return redirect('dashboard')
    
    # Get all funds in portfolio
    holdings = portfolio.holdings.select_related('fund').prefetch_related('lots').all()
    
    if not holdings:
        messages.warning(request, 'No funds in portfolio to refresh.')
        return redirect('dashboard')
    
    logger.info(f"Starting bulk NAV refresh for {len(holdings)} funds")
    
    # Use bulk refresh for faster updates
    try:
        refresh_all_nav_bulk(portfolio)
        
        # Recalculate XIRR for all funds after NAV update
        for holding in holdings:
            try:
                calculate_fund_xirr(holding)
            except Exception as e:
                logger.error(f"Failed to recalculate XIRR for {holding.fund.scheme_name}: {e}")
        
        # Recalculate portfolio XIRR
        try:
            calculate_portfolio_xirr(portfolio)
        except Exception as e:
            logger.error(f"Failed to recalculate portfolio XIRR: {e}")
        
        messages.success(request, f'Successfully refreshed NAV for all {len(holdings)} funds using bulk API!')
        
    except Exception as e:
        logger.error(f"Bulk NAV refresh failed: {e}")
        messages.error(request, f'Failed to refresh NAV: {str(e)}')
    
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
            # Extract the actual error messages from ValidationError dict
            if hasattr(e, 'error_dict'):
                for field, errors in e.error_dict.items():
                    for error in errors:
                        if field == '__all__':
                            messages.error(request, str(error))
                        else:
                            messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
            else:
                messages.error(request, str(e))
        except (ValueError, KeyError):
            messages.error(request, 'Invalid input values.')
        return redirect('settings')
    
    # Handle portfolio reset
    if request.method == 'POST' and 'reset_portfolio' in request.POST:
        try:
            # Get user's portfolio
            user_portfolio = Portfolio.objects.get(user=request.user)
            
            # Count what will be deleted
            funds_count = user_portfolio.holdings.count()
            lots_count = PurchaseLot.objects.filter(portfolio_fund__portfolio=user_portfolio).count()
            cas_imports_count = CASImport.objects.filter(user=request.user).count()
            
            # Delete all related data
            # Delete CAS imports (will cascade delete transactions)
            CASImport.objects.filter(user=request.user).delete()
            # Delete purchase lots
            PurchaseLot.objects.filter(portfolio_fund__portfolio=user_portfolio).delete()
            # Delete portfolio funds
            user_portfolio.holdings.all().delete()
            # Clear XIRR cache
            XIRRCache.objects.filter(portfolio=user_portfolio).delete()
            
            messages.success(request, f'Portfolio reset successfully! Deleted {funds_count} funds, {lots_count} purchase lots, and {cas_imports_count} CAS imports.')
            
        except Portfolio.DoesNotExist:
            messages.error(request, 'No portfolio found to reset.')
        except Exception as e:
            messages.error(request, f'Error resetting portfolio: {str(e)}')
        
        return redirect('settings')
    
    from factsheets.models import FactsheetFetchLog
    recent_logs = FactsheetFetchLog.objects.order_by('-started_at')[:5]

    return render(request, 'portfolio/settings.html', {
        'portfolio': portfolio,
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




# CAS Parser Integration Views

@login_required
def cas_import(request):
    """CAS import landing page - redirect to unified page"""
    return redirect('cas_unified')

@login_required
def cas_unified(request):
    """Unified CAS import page - upload or download"""
    return render(request, 'portfolio/cas_unified.html')


@login_required
def cas_upload(request):
    """Handle CAS PDF upload and processing"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)
    
    if 'cas_file' not in request.FILES:
        return JsonResponse({'error': 'No file uploaded'}, status=400)
    
    cas_file = request.FILES['cas_file']
    password = request.POST.get('password', '').strip()
    
    if not password:
        return JsonResponse({'error': 'Password (PAN) is required'}, status=400)
    
    # Validate file type
    if not cas_file.name.lower().endswith('.pdf'):
        return JsonResponse({'error': 'Only PDF files are allowed'}, status=400)
    
    # Validate file size (max 10MB)
    if cas_file.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'File size must be less than 10MB'}, status=400)
    
    try:
        # Check if this is a duplicate by looking for existing imports first
        import hashlib
        file_hash = hashlib.md5()
        cas_file.seek(0)
        for chunk in iter(lambda: cas_file.read(4096), b""):
            file_hash.update(chunk)
        cas_file.seek(0)
        file_hash = file_hash.hexdigest()
        
        # Check for existing completed import
        from portfolio.models import CASImport
        existing_import = CASImport.objects.filter(
            user=request.user,
            file_hash=file_hash,
            status='COMPLETED'
        ).first()
        
        if existing_import:
            # Return existing import as duplicate
            return JsonResponse({
                'success': True,
                'import_id': existing_import.id,
                'status': 'DUPLICATE',
                'funds_processed': existing_import.funds_processed,
                'transactions_processed': existing_import.transactions_processed,
                'error_message': f'Duplicate file. Original uploaded on {existing_import.created_at}',
                'message': 'Duplicate file detected'
            })
        
        # Process the CAS file
        cas_import = cas_parser_service.parse_cas_pdf(cas_file, password, request.user)
        
        return JsonResponse({
            'success': True,
            'import_id': cas_import.id,
            'status': cas_import.status,
            'funds_processed': cas_import.funds_processed,
            'transactions_processed': cas_import.transactions_processed,
            'message': 'CAS file uploaded successfully. Processing started...'
        })
        
    except Exception as e:
        logger.error(f"Error uploading CAS file: {e}")
        return JsonResponse({'error': f'Processing failed: {str(e)}'}, status=500)


@login_required


@login_required
def cas_import_detail(request, import_id):
    """Show detailed CAS import results"""
    cas_import = get_object_or_404(CASImport, id=import_id, user=request.user)
    transactions = cas_import.transactions.select_related('fund', 'portfolio_fund').order_by('transaction_date')
    
    return render(request, 'portfolio/cas_import_detail.html', {
        'cas_import': cas_import,
        'transactions': transactions
    })




@login_required
def api_cas_import_progress(request):
    """API endpoint to check CAS import progress"""
    import_id = request.GET.get('import_id')
    
    if not import_id:
        return JsonResponse({'error': 'import_id is required'}, status=400)
    
    try:
        cas_import = CASImport.objects.get(id=import_id, user=request.user)
        
        response_data = {
            'status': cas_import.status,
            'funds_processed': cas_import.funds_processed,
            'transactions_processed': cas_import.transactions_processed,
            'errors_count': cas_import.errors_count,
            'completed_at': cas_import.completed_at.isoformat() if cas_import.completed_at else None,
            'error_message': cas_import.error_message
        }
        
        return JsonResponse(response_data)
        
    except CASImport.DoesNotExist:
        return JsonResponse({'error': 'Import not found'}, status=404)


@csrf_exempt
def run_migrations_api(request):
    """API endpoint to run migrations - for production deployment"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)
    
    # Simple security check - commented out for testing
    # if not request.headers.get('Authorization') == 'Bearer migrate-token':
    #     return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        call_command('migrate', '--noinput')
        return JsonResponse({
            'success': True,
            'message': 'Migrations applied successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_POST
def setup_admin_api(request):
    """API endpoint to create admin user - for production deployment"""
    from django.contrib.auth.models import User
    import os
    
    # Get admin credentials from request or use defaults
    username = request.POST.get('username', os.environ.get('ADMIN_USERNAME', 'admin'))
    email = request.POST.get('email', os.environ.get('ADMIN_EMAIL', 'admin@example.com'))
    password = request.POST.get('password', os.environ.get('ADMIN_PASSWORD', 'admin123'))
    
    try:
        # Check if user exists
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_staff': True,
                'is_superuser': True,
            }
        )

        if created:
            user.set_password(password)
            user.save()
            return JsonResponse({
                'status': 'success',
                'message': f'Admin user "{username}" created successfully!',
                'username': username,
                'password': password,
                'warning': 'Please change the password after first login!'
            })
        else:
            # Update existing user
            user.is_staff = True
            user.is_superuser = True
            if password and password != 'admin123':  # Only update if not default
                user.set_password(password)
            user.save()
            return JsonResponse({
                'status': 'success',
                'message': f'Admin user "{username}" updated successfully!'
            })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

