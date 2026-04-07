import logging
from django.core.cache import cache
from .services.rebalance import generate_rebalance_suggestion
from .models import Portfolio, RebalanceSuggestion

logger = logging.getLogger(__name__)

def generate_rebalance_suggestion_task(task_id, portfolio_id):
    """
    Generate rebalancing suggestion with progress tracking
    """
    try:
        # Update progress
        cache.set(f"task_{task_id}_progress", 10, timeout=60)
        
        portfolio = Portfolio.objects.get(id=portfolio_id)
        
        # Update progress
        cache.set(f"task_{task_id}_progress", 30, timeout=60)
        
        # Clear previous suggestions
        RebalanceSuggestion.objects.filter(portfolio=portfolio).delete()
        
        # Update progress
        cache.set(f"task_{task_id}_progress", 50, timeout=60)
        
        # Generate new suggestion
        suggestion = generate_rebalance_suggestion(portfolio)
        
        # Update progress
        cache.set(f"task_{task_id}_progress", 80, timeout=60)
        
        if suggestion:
            # Update progress
            cache.set(f"task_{task_id}_progress", 100, timeout=60)
            cache.set(f"task_{task_id}_result", suggestion.id, timeout=60)
            return suggestion.id
        else:
            cache.set(f"task_{task_id}_progress", 100, timeout=60)
            return None
            
    except Exception as e:
        logger.error(f"Error generating rebalancing suggestion: {e}")
        cache.set(f"task_{task_id}_error", str(e), timeout=60)
        raise
