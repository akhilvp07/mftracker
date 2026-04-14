from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Alert, AlertPreference


@login_required
def alert_list(request):
    # Use intelligent monitor to check if monitoring is needed
    from .intelligent_monitor import intelligent_monitor
    alerts = intelligent_monitor.check_user_alerts(request.user)
    unread = alerts.filter(is_read=False).count()
    return render(request, 'alerts/list.html', {'alerts': alerts, 'unread': unread})


@login_required
@require_POST
def mark_read(request, alert_id):
    alert = get_object_or_404(Alert, pk=alert_id, user=request.user)
    alert.mark_read()
    return redirect('alerts')


@login_required
@require_POST
def mark_all_read(request):
    Alert.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('alerts')


@login_required
@require_POST
def delete_alert(request, alert_id):
    alert = get_object_or_404(Alert, pk=alert_id, user=request.user)
    alert.delete()
    return redirect('alerts')


@login_required
def alert_settings(request):
    preferences, created = AlertPreference.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update email preferences
        preferences.email_nav_changes = request.POST.get('email_nav_changes') == 'on'
        preferences.email_holdings_changes = request.POST.get('email_holdings_changes') == 'on'
        preferences.email_sector_changes = request.POST.get('email_sector_changes') == 'on'
        preferences.email_risk_alerts = request.POST.get('email_risk_alerts') == 'on'
        preferences.email_metadata_changes = request.POST.get('email_metadata_changes') == 'on'
        
        # Update app preferences
        preferences.app_nav_changes = request.POST.get('app_nav_changes') == 'on'
        preferences.app_holdings_changes = request.POST.get('app_holdings_changes') == 'on'
        preferences.app_sector_changes = request.POST.get('app_sector_changes') == 'on'
        preferences.app_risk_alerts = request.POST.get('app_risk_alerts') == 'on'
        preferences.app_metadata_changes = request.POST.get('app_metadata_changes') == 'on'
        
        # Update thresholds
        preferences.nav_threshold = float(request.POST.get('nav_threshold', 5.0))
        preferences.weight_change_threshold = float(request.POST.get('weight_change_threshold', 2.0))
        preferences.sector_change_threshold = float(request.POST.get('sector_change_threshold', 5.0))
        
        # Update daily digest
        preferences.daily_digest_enabled = request.POST.get('daily_digest_enabled') == 'on'
        if preferences.daily_digest_enabled:
            time_str = request.POST.get('digest_time', '09:00')
            hours, minutes = map(int, time_str.split(':'))
            from datetime import time
            preferences.digest_time = time(hour=hours, minute=minutes)
        
        preferences.save()
        messages.success(request, 'Alert preferences updated successfully.')
        return redirect('alert_settings')
    
    return render(request, 'alerts/settings.html', {
        'preferences': preferences,
    })
