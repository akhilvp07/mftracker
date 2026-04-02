from .models import Alert


def unread_alerts_count(request):
    if request.user.is_authenticated:
        count = Alert.objects.filter(user=request.user, is_read=False).count()
        return {'unread_alerts_count': count}
    return {'unread_alerts_count': 0}
