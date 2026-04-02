import logging
from django.core.mail import send_mail
from django.conf import settings
from .models import Alert

logger = logging.getLogger(__name__)


def create_alert(user, fund, alert_type, severity, title, message):
    """Create a persisted alert and attempt email notification."""
    alert = Alert.objects.create(
        user=user,
        fund=fund,
        alert_type=alert_type,
        severity=severity,
        title=title,
        message=message,
    )
    
    # Attempt email if SMTP configured
    if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
        try:
            send_mail(
                subject=f"[MFTracker] {title}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email] if user.email else [],
                fail_silently=True,
            )
            alert.is_emailed = True
            alert.save(update_fields=['is_emailed'])
        except Exception as e:
            logger.warning(f"Email send failed for alert {alert.pk}: {e}")
    
    return alert
