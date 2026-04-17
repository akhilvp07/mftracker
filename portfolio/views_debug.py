from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from funds.models import MutualFund, NAVHistory
from funds.services import calculate_day_change_from_history

@login_required
def debug_fund_day_change(request, scheme_code):
    """Debug view to check day change calculation for a specific fund"""
    try:
        fund = MutualFund.objects.get(scheme_code=scheme_code)
        
        # Get current values
        data = {
            'scheme_code': fund.scheme_code,
            'scheme_name': fund.scheme_name,
            'current_nav': fund.current_nav,
            'nav_date': fund.nav_date,
            'day_change': fund.day_change,
            'day_change_pct': fund.day_change_pct,
        }
        
        # Get previous day's NAV from history
        prev_nav = NAVHistory.objects.filter(
            fund=fund,
            date__lt=fund.nav_date
        ).order_by('-date').first()
        
        if prev_nav:
            data['prev_nav_date'] = prev_nav.date
            data['prev_nav_value'] = prev_nav.nav
            
            # Calculate correct values
            if fund.current_nav and prev_nav.nav:
                correct_change = fund.current_nav - prev_nav.nav
                correct_pct = (correct_change / prev_nav.nav) * 100
                data['calculated_change'] = correct_change
                data['calculated_pct'] = correct_pct
        
        # Get last 5 days of history
        history = NAVHistory.objects.filter(
            fund=fund
        ).order_by('-date')[:5]
        
        data['recent_history'] = [
            {
                'date': h.date,
                'nav': h.nav
            } for h in history
        ]
        
        return JsonResponse(data)
        
    except MutualFund.DoesNotExist:
        return JsonResponse({'error': 'Fund not found'}, status=404)


@login_required
@require_POST
def update_day_change(request, scheme_code):
    """Update day change for a specific fund"""
    try:
        fund = MutualFund.objects.get(scheme_code=scheme_code)
        
        # Calculate day change
        change, change_pct = calculate_day_change_from_history(fund)
        
        if change is not None and change_pct is not None:
            fund.day_change = change
            fund.day_change_pct = change_pct
            fund.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Day change updated successfully',
                'day_change': float(change),
                'day_change_pct': float(change_pct)
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Could not calculate day change - no history available'
            })
            
    except MutualFund.DoesNotExist:
        return JsonResponse({'error': 'Fund not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
