"""
Middleware to auto-refresh NAV data on fund-related pages
"""
from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.urls import resolve
import logging
import time

logger = logging.getLogger(__name__)


class AutoRefreshNavMiddleware(MiddlewareMixin):
    """
    Automatically refresh NAV data when accessing fund-related pages
    Only triggers for pages that don't have their own auto-refresh logic
    """
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Don't process for POST requests, API calls, or static files
        if request.method != 'GET' or request.path.startswith('/static/') or request.path.startswith('/media/'):
            return None
        
        # Check if this is a fund-related view that needs auto-refresh
        url_name = resolve(request.path).url_name
        
        # Views that have their own auto-refresh logic (skip middleware)
        skip_views = {
            'fund_detail',
            'factsheet',
            'edit_fund',
            'add_lot',
            'dashboard',
        }
        
        # Only process views that don't have their own auto-refresh
        if url_name not in skip_views:
            # Check if this view has fund_id that might need refresh
            if 'fund_id' in view_kwargs:
                fund_id = view_kwargs['fund_id']
                
                # Check cache to avoid too frequent checks
                fund_cache_key = f'nav_check_{fund_id}'
                last_check = request.session.get(fund_cache_key, 0)
                current_time = int(time.time())
                
                # Only check if last check was more than 30 minutes ago
                if current_time - last_check > 1800:  # 30 minutes
                    try:
                        from funds.models import MutualFund
                        from .utils import should_refresh_nav
                        
                        fund = MutualFund.objects.get(pk=fund_id)
                        should_refresh, reason = should_refresh_nav(fund)
                        
                        if should_refresh:
                            # Store in session for the view to process
                            request.session['auto_refresh_nav'] = {
                                'fund_id': fund_id,
                                'reason': reason
                            }
                            logger.debug(f"Marked fund {fund_id} for auto-refresh: {reason}")
                            
                    except Exception as e:
                        logger.debug(f"Auto-refresh check failed: {e}")
        
        return None
