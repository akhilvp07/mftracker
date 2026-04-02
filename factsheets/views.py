from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from funds.models import MutualFund
from .models import Factsheet, FactsheetDiff


@login_required
def factsheet_view(request, fund_id):
    fund = get_object_or_404(MutualFund, pk=fund_id)
    factsheets = Factsheet.objects.filter(fund=fund).prefetch_related('holdings', 'sectors')[:6]
    latest_diff = FactsheetDiff.objects.filter(fund=fund).first()
    return render(request, 'factsheets/detail.html', {
        'fund': fund,
        'factsheets': factsheets,
        'latest_diff': latest_diff,
    })


@login_required
@require_POST
def refresh_factsheet(request, fund_id):
    fund = get_object_or_404(MutualFund, pk=fund_id)
    from .fetcher import fetch_factsheet_for_fund
    try:
        fetch_factsheet_for_fund(fund)
        messages.success(request, f'Factsheet refreshed for {fund.scheme_name}.')
    except Exception as e:
        messages.error(request, f'Factsheet refresh failed: {e}')
    return redirect('factsheet', fund_id=fund_id)
