from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from funds.models import MutualFund
from .models import Factsheet, FactsheetDiff
import logging

logger = logging.getLogger(__name__)


@login_required
def factsheet_view(request, fund_id):
    fund = get_object_or_404(MutualFund, pk=fund_id)
    latest_diff = FactsheetDiff.objects.filter(fund=fund).first()
    
    # Get latest factsheet to show any fetch errors
    from datetime import date
    try:
        latest_factsheet = Factsheet.objects.filter(fund=fund).latest('month')
    except Factsheet.DoesNotExist:
        latest_factsheet = None
    
    # Auto-refresh NAV if needed (with caching to avoid too frequent checks)
    from portfolio.utils import auto_refresh_if_needed
    import time
    
    fund_cache_key = f'nav_check_{fund.pk}'
    last_check = request.session.get(fund_cache_key, 0)
    current_time = int(time.time())
    
    # Only check if last check was more than 30 minutes ago
    # Factsheet doesn't need NAV history, just current data
    if current_time - last_check > 1800:  # 30 minutes = 1800 seconds
        auto_refresh_if_needed(request, fund, fetch_history=False)
        request.session[fund_cache_key] = current_time
    
    # Fetch live holdings and sectors from mfdata.in if family_id is available
    mfdata_holdings = None
    mfdata_sectors = None
    
    if fund.family_id:
        from funds.mfdata_service import fetch_family_holdings, fetch_family_sectors
        
        try:
            # Fetch holdings (includes allocation percentages)
            mfdata_holdings = fetch_family_holdings(fund.family_id)
            
            # Fetch sectors
            mfdata_sectors = fetch_family_sectors(fund.family_id)
            
            # Trigger intelligent monitoring for holdings changes
            try:
                from alerts.intelligent_monitor import trigger_holdings_monitoring
                trigger_holdings_monitoring(fund)
            except Exception as e:
                logger.warning(f"Failed to trigger holdings monitoring: {e}")
            
        except Exception as e:
            logger.error(f"Error fetching mfdata.in data for family {fund.family_id}: {e}")
    
    return render(request, 'factsheets/detail.html', {
        'fund': fund,
        'latest_diff': latest_diff,
        'latest_factsheet': latest_factsheet,
        'mfdata_holdings': mfdata_holdings,
        'mfdata_sectors': mfdata_sectors,
    })


@login_required
@require_POST
def refresh_factsheet(request, fund_id):
    fund = get_object_or_404(MutualFund, pk=fund_id)
    from .fetcher import fetch_factsheet_for_fund
    try:
        # Use the enriched fetcher for factsheet data
        fetch_factsheet_for_fund(fund, fetcher_name="enriched")
        
        # Trigger intelligent monitoring for factsheet changes
        try:
            from alerts.intelligent_monitor import trigger_factsheet_monitoring
            trigger_factsheet_monitoring(fund)
        except Exception as e:
            logger.warning(f"Failed to trigger factsheet monitoring: {e}")
        
        messages.success(request, f'Factsheet refreshed for {fund.scheme_name}.')
    except Exception as e:
        messages.error(request, f'Factsheet refresh failed: {e}')
    return redirect('factsheet', fund_id=fund_id)
