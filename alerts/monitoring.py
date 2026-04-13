"""
Enhanced alert monitoring service for mutual fund portfolio changes
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db.models import Q
from funds.models import MutualFund
from portfolio.models import Portfolio
from .services import create_alert
from .models import Alert

logger = logging.getLogger(__name__)


class FundMonitor:
    """Monitor mutual funds for significant changes and create alerts"""
    
    def __init__(self):
        self.thresholds = {
            'nav_change': 5.0,  # 5% NAV change
            'holding_weight_change': 2.0,  # 2% weight change
            'sector_allocation_change': 5.0,  # 5% sector allocation change
            'new_holding_min_weight': 1.0,  # 1% minimum weight for new holding alert
            'expense_ratio_change': 0.1,  # 0.1% expense ratio change
            'aum_change': 10.0,  # 10% AUM change
            'rating_change': 1,  # 1 star rating change
        }
    
    def check_all_funds(self):
        """Run all monitoring checks on all funds"""
        users = User.objects.filter(portfolio__isnull=False).distinct()
        
        for user in users:
            self.check_user_funds(user)
    
    def check_user_funds(self, user):
        """Check all funds in user's portfolio"""
        portfolio_funds = Portfolio.objects.filter(user=user).select_related('fund')
        
        for pf in portfolio_funds:
            self.check_fund_changes(user, pf.fund)
    
    def check_fund_changes(self, user, fund):
        """Check for various types of changes in a fund"""
        if not fund.family_id:
            return
        
        # Get user preferences
        from .models import AlertPreference
        preferences, created = AlertPreference.objects.get_or_create(user=user)
        
        from funds.mfdata_service import (
            fetch_family_holdings,
            fetch_family_sectors,
            fetch_scheme_full_profile
        )
        
        try:
            # Get current data
            current_holdings = fetch_family_holdings(fund.family_id)
            current_sectors = fetch_family_sectors(fund.family_id)
            current_profile = fetch_scheme_full_profile(fund.scheme_code)
            
            if not current_holdings or not current_sectors or not current_profile:
                return
            
            # Check various changes based on preferences
            if preferences.app_nav_changes:
                self.check_nav_changes(user, fund, current_profile, preferences)
            
            if preferences.app_holdings_changes:
                self.check_holding_changes(user, fund, current_holdings, preferences)
            
            if preferences.app_sector_changes:
                self.check_sector_changes(user, fund, current_sectors, preferences)
            
            if preferences.app_metadata_changes:
                self.check_fund_metadata_changes(user, fund, current_profile, preferences)
            
            if preferences.app_risk_alerts:
                self.check_risk_metrics(user, fund)
            
        except Exception as e:
            logger.error(f"Error monitoring fund {fund.scheme_code}: {e}")
    
    def check_nav_changes(self, user, fund, profile, preferences):
        """Check for significant NAV changes"""
        if not fund.current_nav or not profile.get('nav'):
            return
        
        nav_change = abs(profile.get('day_change_pct', 0))
        threshold = float(preferences.nav_threshold)
        
        if nav_change >= threshold:
            direction = 'up' if profile.get('day_change', 0) > 0 else 'down'
            create_alert(
                user=user,
                fund=fund,
                alert_type='nav_update',
                severity='warning' if nav_change >= 10 else 'info',
                title=f"NAV moved {direction} by {nav_change:.2f}%",
                message=f"{fund.scheme_name} NAV changed by {profile.get('day_change_pct', 0):.2f}% to ₹{profile.get('nav'):.4f}"
            )
    
    def check_holding_changes(self, user, fund, holdings, preferences):
        """Check for significant changes in holdings"""
        # Get previous holdings from cache or database
        cache_key = f"holdings_snapshot:{fund.family_id}"
        from django.core.cache import cache
        previous_holdings = cache.get(cache_key)
        
        if previous_holdings and previous_holdings.get('equity_holdings'):
            current_equity = {h['stock_name']: h for h in holdings.get('equity_holdings', [])}
            prev_equity = {h['stock_name']: h for h in previous_holdings.get('equity_holdings', [])}
            
            # Check for new holdings
            for stock_name, holding in current_equity.items():
                if stock_name not in prev_equity and holding.get('weight_pct', 0) >= self.thresholds['new_holding_min_weight']:
                    create_alert(
                        user=user,
                        fund=fund,
                        alert_type='new_holding',
                        severity='info',
                        title=f"New holding: {stock_name}",
                        message=f"{fund.scheme_name} added {stock_name} ({holding.get('weight_pct', 0):.2f}% of portfolio)"
                    )
            
            # Check for exited holdings
            for stock_name, holding in prev_equity.items():
                if stock_name not in current_equity and holding.get('weight_pct', 0) >= 1.0:
                    create_alert(
                        user=user,
                        fund=fund,
                        alert_type='holding_exit',
                        severity='warning',
                        title=f"Exited: {stock_name}",
                        message=f"{fund.scheme_name} sold entire position in {stock_name} (was {holding.get('weight_pct', 0):.2f}%)"
                    )
            
            # Check for significant weight changes
            weight_threshold = float(preferences.weight_change_threshold)
            for stock_name in current_equity:
                if stock_name in prev_equity:
                    current_weight = current_equity[stock_name].get('weight_pct', 0)
                    prev_weight = prev_equity[stock_name].get('weight_pct', 0)
                    weight_change = abs(current_weight - prev_weight)
                    
                    if weight_change >= weight_threshold:
                        direction = 'increased' if current_weight > prev_weight else 'decreased'
                        create_alert(
                            user=user,
                            fund=fund,
                            alert_type='weight_change',
                            severity='info',
                            title=f"Weight change: {stock_name}",
                            message=f"{stock_name} weight {direction} from {prev_weight:.2f}% to {current_weight:.2f}% in {fund.scheme_name}"
                        )
        
        # Save current holdings for next comparison
        cache.set(cache_key, holdings, timeout=86400)  # 24 hours
    
    def check_sector_changes(self, user, fund, sectors, preferences):
        """Check for significant changes in sector allocation"""
        cache_key = f"sectors_snapshot:{fund.family_id}"
        from django.core.cache import cache
        previous_sectors = cache.get(cache_key)
        
        if previous_sectors:
            current_sectors_map = {s['sector']: s['total_weight'] for s in sectors}
            prev_sectors_map = {s['sector']: s['total_weight'] for s in previous_sectors}
            
            sector_threshold = float(preferences.sector_change_threshold)
            for sector, current_weight in current_sectors_map.items():
                prev_weight = prev_sectors_map.get(sector, 0)
                change = abs(current_weight - prev_weight)
                
                if change >= sector_threshold:
                    direction = 'increased' if current_weight > prev_weight else 'decreased'
                    create_alert(
                        user=user,
                        fund=fund,
                        alert_type='sector_change',
                        severity='info',
                        title=f"Sector allocation change: {sector}",
                        message=f"{sector} allocation {direction} from {prev_weight:.1f}% to {current_weight:.1f}% in {fund.scheme_name}"
                    )
        
        # Save current sectors for next comparison
        cache.set(cache_key, sectors, timeout=86400)
    
    def check_fund_metadata_changes(self, user, fund, profile, preferences):
        """Check for changes in fund metadata"""
        changes = []
        
        # Check expense ratio
        if fund.expense_ratio and profile.get('expense_ratio'):
            change = abs(fund.expense_ratio - profile.get('expense_ratio'))
            if change >= self.thresholds['expense_ratio_change']:
                changes.append(f"Expense ratio: {fund.expense_ratio:.2f}% → {profile.get('expense_ratio'):.2f}%")
        
        # Check AUM
        if fund.aum and profile.get('aum'):
            change_pct = abs(fund.aum - profile.get('aum')) / fund.aum * 100
            if change_pct >= self.thresholds['aum_change']:
                changes.append(f"AUM changed by {change_pct:.1f}%")
        
        # Check Morningstar rating
        if fund.morningstar_rating and profile.get('morningstar'):
            if abs(fund.morningstar_rating - profile.get('morningstar')) >= self.thresholds['rating_change']:
                changes.append(f"Rating: {fund.morningstar_rating} → {profile.get('morningstar')} stars")
        
        # Create alert if any significant changes
        if changes:
            create_alert(
                user=user,
                fund=fund,
                alert_type='system',
                severity='info',
                title=f"Fund metadata updated",
                message=f"{fund.scheme_name}\n" + "\n".join(f"• {c}" for c in changes)
            )
    
    def check_risk_metrics(self, user, fund):
        """Check for significant changes in risk metrics"""
        from funds.mfdata_service import fetch_scheme_full_profile
        
        profile = fetch_scheme_full_profile(fund.scheme_code)
        if not profile or not profile.get('ratios'):
            return
        
        ratios = profile['ratios']
        risk_metrics = {
            'sharpe_ratio': ratios.get('returns', {}).get('sharpe_ratio'),
            'beta': ratios.get('risk', {}).get('beta'),
            'std_deviation': ratios.get('risk', {}).get('std_deviation'),
        }
        
        # Check for unusual risk metric values
        alerts = []
        
        if risk_metrics['beta'] and risk_metrics['beta'] > 1.5:
            alerts.append(f"High beta ({risk_metrics['beta']:.2f}) - fund is very volatile")
        
        if risk_metrics['sharpe_ratio'] and risk_metrics['sharpe_ratio'] < -0.5:
            alerts.append(f"Low risk-adjusted returns (Sharpe: {risk_metrics['sharpe_ratio']:.2f})")
        
        if risk_metrics['std_deviation'] and risk_metrics['std_deviation'] > 20:
            alerts.append(f"High volatility (Std Dev: {risk_metrics['std_deviation']:.2f}%)")
        
        for alert_msg in alerts:
            create_alert(
                user=user,
                fund=fund,
                alert_type='system',
                severity='warning',
                title=f"Risk metric alert",
                message=f"{fund.scheme_name}: {alert_msg}"
            )


def check_nav_changes_for_fund(self, user, fund):
    """Check only NAV changes for a specific fund"""
    if not fund.family_id:
        return
        
    # Get user preferences
    from .models import AlertPreference
    preferences, created = AlertPreference.objects.get_or_create(user=user)
    
    if not preferences.app_nav_changes:
        return
        
    from funds.mfdata_service import fetch_scheme_full_profile
    
    try:
        profile = fetch_scheme_full_profile(fund.scheme_code)
        if profile:
            self.check_nav_changes(user, fund, profile, preferences)
    except Exception as e:
        logger.error(f"Error checking NAV for {fund.scheme_code}: {e}")


def check_holding_changes_for_fund(self, user, fund):
    """Check only holdings changes for a specific fund"""
    if not fund.family_id:
        return
        
    # Get user preferences
    from .models import AlertPreference
    preferences, created = AlertPreference.objects.get_or_create(user=user)
    
    if not preferences.app_holdings_changes:
        return
        
    from funds.mfdata_service import fetch_family_holdings
    
    try:
        holdings = fetch_family_holdings(fund.family_id)
        if holdings:
            self.check_holding_changes(user, fund, holdings, preferences)
    except Exception as e:
        logger.error(f"Error checking holdings for {fund.scheme_code}: {e}")


def check_sector_changes_for_fund(self, user, fund):
    """Check only sector changes for a specific fund"""
    if not fund.family_id:
        return
        
    # Get user preferences
    from .models import AlertPreference
    preferences, created = AlertPreference.objects.get_or_create(user=user)
    
    if not preferences.app_sector_changes:
        return
        
    from funds.mfdata_service import fetch_family_sectors
    
    try:
        sectors = fetch_family_sectors(fund.family_id)
        if sectors:
            self.check_sector_changes(user, fund, sectors, preferences)
    except Exception as e:
        logger.error(f"Error checking sectors for {fund.scheme_code}: {e}")


def check_fund_metadata_changes_for_fund(self, user, fund):
    """Check only metadata changes for a specific fund"""
    # Get user preferences
    from .models import AlertPreference
    preferences, created = AlertPreference.objects.get_or_create(user=user)
    
    if not preferences.app_metadata_changes:
        return
        
    from funds.mfdata_service import fetch_scheme_full_profile
    
    try:
        profile = fetch_scheme_full_profile(fund.scheme_code)
        if profile:
            self.check_fund_metadata_changes(user, fund, profile, preferences)
    except Exception as e:
        logger.error(f"Error checking metadata for {fund.scheme_code}: {e}")


# Add methods to FundMonitor class
FundMonitor.check_nav_changes_for_fund = check_nav_changes_for_fund
FundMonitor.check_holding_changes_for_fund = check_holding_changes_for_fund
FundMonitor.check_sector_changes_for_fund = check_sector_changes_for_fund
FundMonitor.check_fund_metadata_changes_for_fund = check_fund_metadata_changes_for_fund


def run_monitoring():
    """Run the monitoring service"""
    monitor = FundMonitor()
    monitor.check_all_funds()
    logger.info("Fund monitoring completed")
