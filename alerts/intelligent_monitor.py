"""
Intelligent monitoring service that triggers based on actual data updates
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.contrib.auth.models import User
from .models import Alert
from .monitoring import FundMonitor
import threading
from django.conf import settings

logger = logging.getLogger(__name__)


class IntelligentMonitor:
    """
    Monitors funds intelligently based on data update triggers
    """
    
    def __init__(self):
        self.fund_monitor = FundMonitor()
        # Cache keys to track last monitoring
        self.monitoring_cache_key = "last_monitoring:{fund_id}"
        self.monitoring_cooldown = 3600  # 1 hour cooldown per fund
        
    def trigger_on_nav_update(self, fund):
        """
        Trigger monitoring when NAV is updated
        """
        # Check if monitoring is enabled
        if not getattr(settings, 'INTELLIGENT_MONITORING_ENABLED', True):
            return
            
        if not self._should_monitor(fund):
            return
            
        logger.info(f"Triggering background monitoring for {fund.scheme_code} due to NAV update")
        
        # Check if should run in background
        if getattr(settings, 'BACKGROUND_MONITORING', True):
            # Run in background thread to avoid blocking
            thread = threading.Thread(
                target=self._monitor_nav_background,
                args=(fund,),
                daemon=True
            )
            thread.start()
        else:
            # Run synchronously (for debugging)
            self._monitor_nav_background(fund)
    
    def _monitor_nav_background(self, fund):
        """
        Background thread for NAV monitoring
        """
        try:
            # Get all users who have this fund
            from portfolio.models import Portfolio
            users = User.objects.filter(
                portfolio__holdings__fund=fund
            ).distinct()
            
            for user in users:
                try:
                    # Only check NAV-related changes
                    self.fund_monitor.check_nav_changes_for_fund(user, fund)
                    self._mark_monitored(fund)
                except Exception as e:
                    logger.error(f"Error monitoring NAV for {fund.scheme_code}: {e}")
        except Exception as e:
            logger.error(f"Background NAV monitoring error: {e}")
    
    def trigger_on_holdings_update(self, fund):
        """
        Trigger monitoring when holdings data is updated
        """
        # Check if monitoring is enabled
        if not getattr(settings, 'INTELLIGENT_MONITORING_ENABLED', True):
            return
            
        if not self._should_monitor(fund):
            return
            
        logger.info(f"Triggering background monitoring for {fund.scheme_code} due to holdings update")
        
        # Check if should run in background
        if getattr(settings, 'BACKGROUND_MONITORING', True):
            # Run in background thread to avoid blocking
            thread = threading.Thread(
                target=self._monitor_holdings_background,
                args=(fund,),
                daemon=True
            )
            thread.start()
        else:
            # Run synchronously (for debugging)
            self._monitor_holdings_background(fund)
    
    def _monitor_holdings_background(self, fund):
        """
        Background thread for holdings monitoring
        """
        try:
            # Get all users who have this fund
            from portfolio.models import Portfolio
            users = User.objects.filter(
                portfolio__holdings__fund=fund
            ).distinct()
            
            for user in users:
                try:
                    # Check holdings and sector changes
                    self.fund_monitor.check_holding_changes_for_fund(user, fund)
                    self.fund_monitor.check_sector_changes_for_fund(user, fund)
                    self._mark_monitored(fund)
                except Exception as e:
                    logger.error(f"Error monitoring holdings for {fund.scheme_code}: {e}")
        except Exception as e:
            logger.error(f"Background holdings monitoring error: {e}")
    
    def trigger_on_factsheet_update(self, fund):
        """
        Trigger monitoring when factsheet is updated
        """
        # Check if monitoring is enabled
        if not getattr(settings, 'INTELLIGENT_MONITORING_ENABLED', True):
            return
            
        if not self._should_monitor(fund):
            return
            
        logger.info(f"Triggering background monitoring for {fund.scheme_code} due to factsheet update")
        
        # Check if should run in background
        if getattr(settings, 'BACKGROUND_MONITORING', True):
            # Run in background thread to avoid blocking
            thread = threading.Thread(
                target=self._monitor_factsheet_background,
                args=(fund,),
                daemon=True
            )
            thread.start()
        else:
            # Run synchronously (for debugging)
            self._monitor_factsheet_background(fund)
    
    def _monitor_factsheet_background(self, fund):
        """
        Background thread for factsheet monitoring
        """
        try:
            # Get all users who have this fund
            from portfolio.models import Portfolio
            users = User.objects.filter(
                portfolio__holdings__fund=fund
            ).distinct()
            
            for user in users:
                try:
                    # Check metadata changes
                    self.fund_monitor.check_fund_metadata_changes_for_fund(user, fund)
                    self._mark_monitored(fund)
                except Exception as e:
                    logger.error(f"Error monitoring metadata for {fund.scheme_code}: {e}")
        except Exception as e:
            logger.error(f"Background factsheet monitoring error: {e}")
    
    def _should_monitor(self, fund):
        """
        Check if we should monitor this fund (cooldown period)
        """
        cache_key = self.monitoring_cache_key.format(fund_id=fund.pk)
        last_monitoring = cache.get(cache_key)
        if last_monitoring:
            import time
            if time.time() - last_monitoring < self.monitoring_cooldown:
                return False
        return True
    
    def _mark_monitored(self, fund):
        """
        Mark that we've monitored this fund recently
        """
        cache_key = self.monitoring_cache_key.format(fund_id=fund.pk)
        import time
        cache.set(cache_key, time.time(), timeout=self.monitoring_cooldown)
    
    def check_user_alerts(self, user):
        """
        Check and return alerts for a specific user
        This is called when user visits the alerts page
        """
        from .models import Alert
        alerts = Alert.objects.filter(
            user=user
        ).select_related('fund').order_by('-created_at')
        
        # Trigger monitoring for user's funds if needed
        self._check_if_monitoring_needed(user)
        
        return alerts
    
    def _check_if_monitoring_needed(self, user):
        """
        Check if any of the user's funds need monitoring
        """
        from portfolio.models import Portfolio
        
        # Check if user has any recent alerts
        recent_alerts = Alert.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).exists()
        
        if recent_alerts:
            return  # User already has recent alerts
        
        # Check each fund in user's portfolio
        portfolio_funds = Portfolio.objects.filter(
            user=user
        ).select_related('fund')
        
        for pf in portfolio_funds:
            if self._should_monitor(pf.fund):
                # Trigger full monitoring for this fund
                try:
                    self.fund_monitor.check_fund_changes(user, pf.fund)
                    self._mark_monitored(pf.fund)
                except Exception as e:
                    logger.error(f"Error monitoring {pf.fund.scheme_code}: {e}")


# Global instance
intelligent_monitor = IntelligentMonitor()


def trigger_nav_monitoring(fund):
    """Convenience function to trigger NAV monitoring"""
    intelligent_monitor.trigger_on_nav_update(fund)


def trigger_holdings_monitoring(fund):
    """Convenience function to trigger holdings monitoring"""
    intelligent_monitor.trigger_on_holdings_update(fund)


def trigger_factsheet_monitoring(fund):
    """Convenience function to trigger factsheet monitoring"""
    intelligent_monitor.trigger_on_factsheet_update(fund)
