from decimal import Decimal, ROUND_DOWN
from django.db import transaction
from portfolio.models import AssetAllocation, RebalanceSuggestion, RebalanceAction, PortfolioFund
from funds.models import MutualFund
import logging

logger = logging.getLogger(__name__)


def get_fund_category(fund):
    """Categorize fund based on its category and type"""
    category = fund.category.lower() if fund.category else ''
    fund_category = fund.fund_category.lower() if fund.fund_category else ''
    fund_type = fund.fund_type.lower() if fund.fund_type else ''
    name = fund.scheme_name.lower() if fund.scheme_name else ''
    
    # Special cases based on fund name - these have priority
    if 'gold' in name:
        asset_class = 'gold'
    elif 'silver' in name:
        asset_class = 'gold'  # Treat silver as gold for allocation purposes
    elif 'liquid' in name:
        asset_class = 'debt'
    elif any(keyword in name for keyword in ['nasdaq', 'us', 'world']):
        asset_class = 'equity'
    elif 'elss' in name or 'tax saver' in name:
        asset_class = 'equity'  # ELSS/Tax Saver funds are equity funds
    # Asset class classification - check both category and fund_category
    # But only if not already classified by name
    elif ('equity' in category or 'equity' in fund_category or 
          ('fund of funds' in category or 'fund of funds' in fund_category) and 
          'gold' not in name and 'silver' not in name or
          'sectoral' in category or 'thematic' in category or
          'sectoral' in fund_category or 'thematic' in fund_category):
        asset_class = 'equity' 
    elif (('debt' in category or 'debt' in fund_category or 'bond' in category or 'bond' in fund_category or 
           'gilt' in category or 'gilt' in fund_category or 'duration' in category or 'duration' in fund_category or 
           'income' in category or 'income' in fund_category or 
           'liquid' in category or 'liquid' in fund_category or 'money market' in category or 'money market' in fund_category or
           'corporate bond' in category or 'corporate bond' in fund_category or 'credit risk' in category or 'credit risk' in fund_category or
           'banking & psu' in category or 'banking & psu' in fund_category or 'floating rate' in category or 'floating rate' in fund_category or
           'dynamic bond' in category or 'dynamic bond' in fund_category or 'ultra short' in category or 'ultra short' in fund_category or
           'low duration' in category or 'low duration' in fund_category)):
        if 'liquid' in category or 'liquid' in name or 'liquid' in fund_category:
            asset_class = 'debt'  # Will be marked as liquid below
        else:
            asset_class = 'debt'
    elif ('gold' in category or 'gold' in fund_category or 'commodity' in category or 'commodity' in fund_category):
        asset_class = 'gold'
    elif ('hybrid' in category or 'hybrid' in fund_category or 'balanced' in category or 'balanced' in fund_category or 
          'arbitrage' in category or 'arbitrage' in fund_category):
        # For hybrid funds, check the type to determine asset class
        if 'equity' in fund_type:
            asset_class = 'equity'
        elif 'debt' in fund_type:
            asset_class = 'debt'
        else:
            asset_class = 'equity'  # Default to equity for aggressive hybrid
    else:
        asset_class = 'equity'  # Default assumption
    
    # Market cap classification for equity funds
    market_cap = None
    if asset_class == 'equity':
        # Check both category fields for market cap
        combined_category = f"{category} {fund_category}"
        if 'large cap' in combined_category or 'largecap' in combined_category:
            market_cap = 'large'
        elif 'mid cap' in combined_category or 'midcap' in combined_category:
            market_cap = 'mid'
        elif 'small cap' in combined_category or 'smallcap' in combined_category:
            market_cap = 'small'
        elif 'multi cap' in combined_category or 'multicap' in combined_category or 'flexi cap' in combined_category:
            # For multi-cap funds, distribute proportionally or default to large
            # For simplicity, we'll classify based on their primary allocation
            market_cap = 'large'  # Most multi-cap funds lean towards large cap
        else:
            # Default classification based on fund type/name
            if 'elss' in name or 'tax saver' in name:
                market_cap = 'large'  # ELSS funds typically large-cap oriented
            elif 'index' in combined_category:
                if 'nifty 50' in name or 'nifty next 50' in name:
                    market_cap = 'large'
                elif 'nifty midcap' in name or 'midcap' in name:
                    market_cap = 'mid'
                elif 'nifty smallcap' in name or 'smallcap' in name:
                    market_cap = 'small'
                else:
                    market_cap = 'large'  # Default index funds to large
            else:
                market_cap = 'large'  # Default to large cap
    
    # Sub-category for debt funds
    debt_subcategory = None
    if asset_class == 'debt':
        if 'liquid' in category or 'liquid' in name:
            debt_subcategory = 'liquid'
        elif 'ultra short' in category or 'ultra short' in name:
            debt_subcategory = 'ultra_short'
        elif 'low duration' in category or 'low duration' in name:
            debt_subcategory = 'low_duration'
        elif 'short duration' in category or 'short duration' in name:
            debt_subcategory = 'short_duration'
        elif 'money market' in category or 'money market' in name:
            debt_subcategory = 'money_market'
    
    return asset_class, market_cap, debt_subcategory if asset_class == 'debt' else None


def calculate_current_allocation(portfolio):
    """Calculate current asset allocation of the portfolio"""
    total_value = Decimal('0')
    asset_values = {'equity': Decimal('0'), 'debt': Decimal('0'), 'gold': Decimal('0')}
    equity_cap_values = {'large': Decimal('0'), 'mid': Decimal('0'), 'small': Decimal('0')}
    
    for pf in portfolio.holdings.all():
        value = pf.current_value
        total_value += value
        
        asset_class, market_cap, _ = get_fund_category(pf.fund)
        
        # Add to asset class allocation
        if asset_class in asset_values:
            asset_values[asset_class] += value
        
        # Add to equity cap allocation if it's an equity fund
        if asset_class == 'equity' and market_cap in equity_cap_values:
            equity_cap_values[market_cap] += value
    
    # Calculate percentages
    allocation = {}
    if total_value > 0:
        allocation['equity'] = (asset_values['equity'] / total_value) * Decimal('100')
        allocation['debt'] = (asset_values['debt'] / total_value) * Decimal('100')
        allocation['gold'] = (asset_values['gold'] / total_value) * Decimal('100')
        
        # Equity cap percentages (as percentage of total equity)
        total_equity = asset_values['equity']
        if total_equity > 0:
            allocation['large_cap'] = (equity_cap_values['large'] / total_equity) * Decimal('100')
            allocation['mid_cap'] = (equity_cap_values['mid'] / total_equity) * Decimal('100')
            allocation['small_cap'] = (equity_cap_values['small'] / total_equity) * Decimal('100')
        else:
            allocation['large_cap'] = allocation['mid_cap'] = allocation['small_cap'] = Decimal('0')
    
    return allocation, total_value


def generate_rebalance_suggestion(portfolio):
    """Generate rebalancing suggestions for a portfolio"""
    try:
        allocation = AssetAllocation.objects.get(portfolio=portfolio)
    except AssetAllocation.DoesNotExist:
        # Create default allocation if it doesn't exist
        allocation = AssetAllocation.objects.create(portfolio=portfolio)
    
    current_allocation, total_value = calculate_current_allocation(portfolio)
    
    # Check if rebalancing is needed
    threshold = allocation.rebalance_threshold
    
    # Check asset class deviations
    asset_deviations = {}
    for asset in ['equity', 'debt', 'gold']:
        target = getattr(allocation, f'{asset}_percentage')
        current = current_allocation.get(asset, Decimal('0'))
        deviation = abs(current - target)
        asset_deviations[asset] = deviation
    
    # Check equity cap deviations
    equity_deviations = {}
    for cap in ['large_cap', 'mid_cap', 'small_cap']:
        target = getattr(allocation, f'{cap}_percentage')
        current = current_allocation.get(cap, Decimal('0'))
        deviation = abs(current - target)
        equity_deviations[cap] = deviation
    
    # If no significant deviations, no rebalancing needed
    max_deviation = max(max(asset_deviations.values()), max(equity_deviations.values()))
    if max_deviation < threshold:
        return None
    
    # Create rebalance suggestion
    with transaction.atomic():
        suggestion = RebalanceSuggestion.objects.create(
            portfolio=portfolio,
            current_equity=current_allocation.get('equity', Decimal('0')),
            current_debt=current_allocation.get('debt', Decimal('0')),
            current_gold=current_allocation.get('gold', Decimal('0')),
            target_equity=allocation.equity_percentage,
            target_debt=allocation.debt_percentage,
            target_gold=allocation.gold_percentage,
            total_value=total_value
        )
        
        # Calculate current values in each asset class
        current_values = {}
        for pf in portfolio.holdings.all():
            value = pf.current_value
            asset_class, market_cap, _ = get_fund_category(pf.fund)
            if asset_class not in current_values:
                current_values[asset_class] = Decimal('0')
            current_values[asset_class] += value
        
        # Generate buy/sell actions
        actions = []
        
        # First, determine what needs to be sold and bought
        target_values = {}
        for asset_class in ['equity', 'debt', 'gold']:
            target_percentage = getattr(allocation, f'{asset_class}_percentage')
            target_values[asset_class] = total_value * (target_percentage / Decimal('100'))
        
        # Calculate sell and buy needs
        sell_needs = {}
        buy_needs = {}
        
        for asset_class, target_value in target_values.items():
            current_value = current_values.get(asset_class, Decimal('0'))
            if current_value > target_value + (total_value * Decimal('0.01')):  # 1% threshold
                sell_needs[asset_class] = current_value - target_value
            elif current_value < target_value - (total_value * Decimal('0.01')):
                buy_needs[asset_class] = target_value - current_value
        
        # Generate SELL actions - Asset Class Level
        actual_sell_amount = Decimal('0')
        for asset_class, sell_amount in sell_needs.items():
            # Find funds in this asset class to sell
            asset_funds = [pf for pf in portfolio.holdings.all() 
                          if get_fund_category(pf.fund)[0] == asset_class]
            
            if asset_funds:
                current_value = current_values[asset_class]
                
                # Special handling for equity - use cap-based selling only if equity is at target
                if asset_class == 'equity':
                    # Check if equity is close to target
                    equity_target = target_values.get('equity', current_value)
                    equity_diff_pct = abs(current_value - equity_target) / equity_target * 100 if equity_target > 0 else 100
                    
                    if equity_diff_pct < 2:  # Equity is at target, use cap-based selling
                        # Calculate current cap distribution
                        cap_values = {'large': Decimal('0'), 'mid': Decimal('0'), 'small': Decimal('0')}
                        cap_funds = {'large': [], 'mid': [], 'small': []}
                        
                        for pf in asset_funds:
                            _, market_cap, _ = get_fund_category(pf.fund)
                            cap_values[market_cap] += pf.current_value
                            cap_funds[market_cap].append(pf)
                        
                        # Calculate target cap values based on allocation targets
                        equity_target = target_values['equity']
                        cap_targets = {
                            'large': equity_target * (allocation.large_cap_percentage / Decimal('100')),
                            'mid': equity_target * (allocation.mid_cap_percentage / Decimal('100')),
                            'small': equity_target * (allocation.small_cap_percentage / Decimal('100'))
                        }
                        
                        # Calculate how much to sell per cap
                        cap_sell_needs = {}
                        for cap in ['large', 'mid', 'small']:
                            if cap_values[cap] > cap_targets[cap]:
                                cap_sell_needs[cap] = cap_values[cap] - cap_targets[cap]
                        
                        # Sell within each cap category
                        for cap, cap_sell_amount in cap_sell_needs.items():
                            if cap_funds[cap] and cap_sell_amount > 0:
                                cap_total = cap_values[cap]
                                for pf in cap_funds[cap]:
                                    fund_ratio = pf.current_value / cap_total
                                    fund_sell_amount = cap_sell_amount * fund_ratio
                                    
                                    if fund_sell_amount > 0:
                                        action = RebalanceAction(
                                            suggestion=suggestion,
                                            fund=pf.fund,
                                            action='SELL',
                                            amount=fund_sell_amount,
                                            reason=f"Reduce {cap} cap holdings from {float(cap_values[cap]/equity_target*100):.1f}% to {float(getattr(allocation, f'{cap}_cap_percentage')):.1f}% of equity"
                                        )
                                        
                                        if pf.fund.current_nav:
                                            action.units = (fund_sell_amount / pf.fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                                        
                                        actions.append(action)
                                        actual_sell_amount += fund_sell_amount
                    else:
                        # Smart proportional selling for equity when not at target
                        # Prioritize selling from caps that are over their targets
                        cap_values = {'large': Decimal('0'), 'mid': Decimal('0'), 'small': Decimal('0')}
                        cap_funds = {'large': [], 'mid': [], 'small': []}
                        
                        for pf in asset_funds:
                            _, market_cap, _ = get_fund_category(pf.fund)
                            cap_values[market_cap] += pf.current_value
                            cap_funds[market_cap].append(pf)
                        
                        # Calculate target cap values based on equity target
                        equity_target_value = target_values['equity']
                        cap_targets = {
                            'large': equity_target_value * (allocation.large_cap_percentage / Decimal('100')),
                            'mid': equity_target_value * (allocation.mid_cap_percentage / Decimal('100')),
                            'small': equity_target_value * (allocation.small_cap_percentage / Decimal('100'))
                        }
                        
                        # Calculate how much each cap is over/under target (in absolute terms)
                        cap_imbalances = {}
                        for cap in ['large', 'mid', 'small']:
                            current = cap_values[cap]
                            target = cap_targets[cap]
                            cap_imbalances[cap] = current - target  # Positive = over, Negative = under
                        
                        # Priority 1: Sell from over-weighted caps first
                        sell_from_overweighted = {}
                        remaining_sell = sell_amount
                        
                        for cap in ['large', 'mid', 'small']:
                            if cap_imbalances[cap] > 0 and remaining_sell > 0:
                                # This cap is over target, sell from it first
                                can_sell = min(cap_imbalances[cap], remaining_sell)
                                sell_from_overweighted[cap] = can_sell
                                remaining_sell -= can_sell
                        
                        # Priority 2: If still need to sell more, sell proportionally from all caps
                        if remaining_sell > 0:
                            total_remaining_value = sum(cap_values[cap] for cap in ['large', 'mid', 'small'])
                            for cap in ['large', 'mid', 'small']:
                                if total_remaining_value > 0:
                                    proportional_sell = remaining_sell * (cap_values[cap] / total_remaining_value)
                                    sell_from_overweighted[cap] = sell_from_overweighted.get(cap, 0) + proportional_sell
                        
                        # Execute the selling
                        for cap, sell_amount in sell_from_overweighted.items():
                            if cap_funds[cap] and sell_amount > 0:
                                cap_total = cap_values[cap]
                                for pf in cap_funds[cap]:
                                    fund_ratio = pf.current_value / cap_total
                                    fund_sell_amount = sell_amount * fund_ratio
                                    
                                    if fund_sell_amount > 0:
                                        # Calculate current cap percentage within equity
                                        cap_current_pct = (cap_values[cap] / current_value * 100) if current_value > 0 else 0
                                        # Get the cap target percentage
                                        cap_target_pct = getattr(allocation, f'{cap}_cap_percentage')
                                        
                                        # Determine the reason
                                        if cap_imbalances[cap] > 0 and fund_sell_amount <= cap_imbalances[cap]:
                                            reason = f"Reduce {cap} cap holdings ({cap_current_pct:.1f}% of equity) to reach {cap} cap target of {cap_target_pct:.1f}%"
                                        else:
                                            reason = f"Reduce {cap} cap holdings ({cap_current_pct:.1f}% of equity) to reach overall equity target of {float(getattr(allocation, f'{asset_class}_percentage')):.1f}%"
                                        
                                        action = RebalanceAction(
                                            suggestion=suggestion,
                                            fund=pf.fund,
                                            action='SELL',
                                            amount=fund_sell_amount,
                                            reason=reason
                                        )
                                        
                                        if pf.fund.current_nav:
                                            action.units = (fund_sell_amount / pf.fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                                        
                                        actions.append(action)
                                        actual_sell_amount += fund_sell_amount
                else:
                    # Regular proportional selling for non-equity
                    for pf in asset_funds:
                        fund_ratio = pf.current_value / current_value
                        fund_sell_amount = sell_amount * fund_ratio
                        
                        if fund_sell_amount > 0:
                            action = RebalanceAction(
                                suggestion=suggestion,
                                fund=pf.fund,
                                action='SELL',
                                amount=fund_sell_amount,
                                reason=f"Reduce {asset_class} allocation from {float(current_allocation.get(asset_class, 0)):.1f}% to {float(getattr(allocation, f'{asset_class}_percentage'))}%"
                            )
                            
                            if pf.fund.current_nav:
                                action.units = (fund_sell_amount / pf.fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                            
                            actions.append(action)
                            actual_sell_amount += fund_sell_amount
        
        # Calculate total amount available from sells
        total_sell_amount = sum(sell_needs.values())
        
        # Generate BUY actions using proceeds from sells
        if actual_sell_amount > 0 and buy_needs:
            # Distribute ALL sell proceeds proportionally to buy needs
            total_buy_needed = sum(buy_needs.values())
            
            # Scale down buy amounts to match actual sell proceeds
            for asset_class, needed_amount in buy_needs.items():
                # Allocate proportionally from actual sell proceeds
                allocated_amount = (needed_amount / total_buy_needed) * actual_sell_amount
                
                if allocated_amount > 0:
                    # Find existing funds in this asset class to buy more of
                    existing_funds = []
                    for pf in portfolio.holdings.all():
                        fund_asset_class, _, _ = get_fund_category(pf.fund)
                        if fund_asset_class == asset_class:
                            existing_funds.append(pf.fund)
                    
                    # Only suggest buying if we already have funds in this asset class
                    if existing_funds:
                        # Sort existing funds by current value (buy more of the largest holdings)
                        existing_funds.sort(key=lambda f: next((pf.current_value for pf in portfolio.holdings.all() if pf.fund == f), 0), reverse=True)
                        
                        # Buy the top existing fund
                        best_fund = existing_funds[0]
                        
                        action = RebalanceAction(
                            suggestion=suggestion,
                            fund=best_fund,
                            action='BUY',
                            amount=allocated_amount,
                            reason=f"Increase {asset_class} allocation using proceeds from sales (target: {(allocated_amount/total_sell_amount*100):.1f}% of proceeds)"
                        )
                        
                        if best_fund.current_nav:
                            action.units = (allocated_amount / best_fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                        
                        actions.append(action)
                    else:
                        # No existing funds in this asset class
                        action = RebalanceAction(
                            suggestion=suggestion,
                            fund=None,
                            action='BUY',
                            amount=allocated_amount,
                            reason=f"No {asset_class} funds in portfolio. Please add {asset_class} funds manually."
                        )
                        actions.append(action)
        
        # Handle equity cap rebalancing (when equity is at target but caps are not)
        if 'equity' in current_values:
            # Check if we need to rebalance caps within equity
            equity_target = target_values.get('equity', current_values.get('equity', Decimal('0')))
            equity_current = current_values['equity']
            
            # Only rebalance caps if equity allocation is close to target (within 2%)
            equity_diff_pct = abs(equity_current - equity_target) / equity_target * 100 if equity_target > 0 else 100
            
            if equity_diff_pct < 2:  # Equity is at target, check caps
                equity_cap_targets = {
                    'large': equity_target * (allocation.large_cap_percentage / Decimal('100')),
                    'mid': equity_target * (allocation.mid_cap_percentage / Decimal('100')),
                    'small': equity_target * (allocation.small_cap_percentage / Decimal('100'))
                }
                
                # Calculate current cap values
                cap_values = {'large': Decimal('0'), 'mid': Decimal('0'), 'small': Decimal('0')}
                cap_funds = {'large': [], 'mid': [], 'small': []}
                
                for pf in portfolio.holdings.all():
                    asset_class, market_cap, _ = get_fund_category(pf.fund)
                    if asset_class == 'equity':
                        cap_values[market_cap] += pf.current_value
                        cap_funds[market_cap].append(pf)
                
                # Find cap imbalances within equity
                cap_sell_needs = {}
                cap_buy_needs = {}
                for cap in ['large', 'mid', 'small']:
                    current = cap_values[cap]
                    target = equity_cap_targets[cap]
                    if current > target + (equity_target * Decimal('0.02')):  # 2% threshold
                        cap_sell_needs[cap] = current - target
                    elif current < target - (equity_target * Decimal('0.02')):
                        cap_buy_needs[cap] = target - current
                
                # Generate SELL actions for overweighted caps
                for cap, sell_amount in cap_sell_needs.items():
                    if cap_funds[cap] and sell_amount > 0:
                        cap_total = cap_values[cap]
                        for pf in cap_funds[cap]:
                            fund_ratio = pf.current_value / cap_total
                            fund_sell_amount = sell_amount * fund_ratio
                            
                            if fund_sell_amount > 0:
                                action = RebalanceAction(
                                    suggestion=suggestion,
                                    fund=pf.fund,
                                    action='SELL',
                                    amount=fund_sell_amount,
                                    reason=f"Reduce {cap} cap from {float(cap_values[cap]/equity_target*100):.1f}% to {float(getattr(allocation, f'{cap}_cap_percentage')):.1f}% of equity"
                                )
                                
                                if pf.fund.current_nav:
                                    action.units = (fund_sell_amount / pf.fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                                
                                actions.append(action)
                                actual_sell_amount += fund_sell_amount
                
                # Generate BUY actions for underweighted caps using sell proceeds
                if cap_sell_needs and cap_buy_needs:
                    total_sell = sum(cap_sell_needs.values())
                    total_buy_needed = sum(cap_buy_needs.values())
                    
                    for cap, buy_amount in cap_buy_needs.items():
                        # Allocate proportionally from sell proceeds
                        allocated_amount = (buy_amount / total_buy_needed) * total_sell
                        
                        if cap_funds[cap] and allocated_amount > 0:
                            # Buy the largest holding in this cap
                            cap_funds[cap].sort(key=lambda pf: pf.current_value, reverse=True)
                            best_fund = cap_funds[cap][0]
                            
                            action = RebalanceAction(
                                suggestion=suggestion,
                                fund=best_fund,
                                action='BUY',
                                amount=allocated_amount,
                                reason=f"Increase {cap} cap to target {float(getattr(allocation, f'{cap}_cap_percentage')):.1f}% of equity"
                            )
                            
                            if best_fund.current_nav:
                                action.units = (allocated_amount / best_fund.current_nav).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
                            
                            actions.append(action)
        
        # Bulk create all actions
        if actions:
            RebalanceAction.objects.bulk_create(actions)
        
        suggestion.save()
        return suggestion


def get_rebalance_summary(suggestion):
    """Get a summary of the rebalancing suggestion"""
    actions = suggestion.actions.all()
    
    buys = actions.filter(action='BUY')
    sells = actions.filter(action='SELL')
    
    total_buy_amount = sum(a.amount for a in buys)
    total_sell_amount = sum(a.amount for a in sells)
    
    return {
        'total_buy_amount': total_buy_amount,
        'total_sell_amount': total_sell_amount,
        'net_amount': total_buy_amount - total_sell_amount,
        'buy_actions': buys,
        'sell_actions': sells,
        'total_actions': len(actions)
    }
