import logging
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from funds.services import refresh_all_navs

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["POST"])
def cron_refresh_nav(request):
    """Cron job endpoint to refresh NAV for all portfolio funds."""
    # Verify the request is from Vercel cron
    auth_header = request.headers.get('Authorization')
    cron_secret = getattr(settings, 'CRON_SECRET', None)
    
    if not cron_secret or auth_header != f'Bearer {cron_secret}':
        logger.warning(f"Unauthorized cron attempt from {request.META.get('REMOTE_ADDR')}")
        return HttpResponseForbidden("Unauthorized")
    
    logger.info("Cron job: Starting NAV refresh...")
    
    try:
        success, errors = refresh_all_navs()
        logger.info(f"Cron job: NAV refresh complete - {success} success, {errors} errors")
        return HttpResponse(f"NAV refresh complete: {success} success, {errors} errors")
    except Exception as e:
        logger.error(f"Cron job: NAV refresh failed - {str(e)}")
        return HttpResponse(f"NAV refresh failed: {str(e)}", status=500)
