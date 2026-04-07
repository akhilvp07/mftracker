"""
Template tags for Groww integration
"""
from django import template
import logging

register = template.Library()
logger = logging.getLogger(__name__)


@register.filter
def groww_url(fund):
    """
    Generate Groww URL for a mutual fund
    """
    try:
        from ..groww_utils import get_groww_url
        url = get_groww_url(fund.scheme_name, fund.isin)
        return url or "#"
    except Exception as e:
        logger.error(f"Error generating Groww URL for {fund.scheme_name}: {e}")
        # Fallback to simple slugified URL
        return f"https://groww.in/mutual-funds/{fund.scheme_name.lower().replace(' ', '-')}"
