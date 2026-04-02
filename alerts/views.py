from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import Alert


@login_required
def alert_list(request):
    alerts = Alert.objects.filter(user=request.user).select_related('fund')
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
