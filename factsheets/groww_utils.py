"""
Utilities for generating Groww URLs for mutual funds
"""
import requests
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)


def get_groww_url(fund_name, isin=None):
    """
    Get the exact Groww URL for a mutual fund using Groww's search API
    
    Args:
        fund_name: Name of the mutual fund
        isin: ISIN code (optional, can help with search accuracy)
    
    Returns:
        Full Groww URL or None if not found
    """
    # Check cache first
    cache_key = f"groww_url:{fund_name}:{isin or ''}"
    cached_url = cache.get(cache_key)
    if cached_url:
        logger.debug(f"Using cached Groww URL for {fund_name}")
        return cached_url
    
    # Known fund renames - try both old and new names
    renamed_funds = {
        'SBI Small Cap Fund': 'SBI Small Midcap Fund',
        'SBI Small Cap Fund Direct': 'SBI Small Midcap Fund Direct',
        'Motilal Oswal Midcap Fund': 'Motilal Oswal Most Focused Midcap 30 Fund',
        'Axis Midcap Fund': 'Axis Midcap Fund',
        'Axis Long Term Equity Fund': 'Axis Equity Fund',
        # Add more as discovered
    }
    
    # Special URL patterns for certain AMCs
    url_patterns = {
        'ICICI Prudential': [
            {
                # Handle full fund names with plan types
                # Convert: ICICI Prudential Short Term Fund - Direct Plan - Growth Option
                # To: icici-prudential-short-term-plan-direct-growth
                'pattern': r'ICICI Prudential (.+) Fund - (.+) Plan - (.+) Option',
                'replacement': r'icici-prudential-\1-plan-\2-\3',
                'post_process': True
            },
            {
                # Handle simpler case without "Option"
                'pattern': r'ICICI Prudential (.+) Fund - (.+) Plan - (.+)',
                'replacement': r'icici-prudential-\1-plan-\2-\3',
                'post_process': True
            }
        ],
        'HDFC': [
            {
                # Many HDFC funds use special patterns
                'pattern': r'HDFC (.+)',
                'replacement': r'hdfc-\1',
                'post_process': True
            }
        ],
        'SBI': [
            {
                # Handle renamed SBI Small Cap to Small Midcap
                'pattern': r'SBI Small Cap Fund',
                'replacement': r'sbi-small-midcap-fund',
                'post_process': True
            },
            {
                # SBI funds often have special naming
                'pattern': r'SBI (.+) Fund',
                'replacement': r'sbi-\1-fund',
                'post_process': True
            }
        ],
        'Motilal Oswal': [
            {
                # Handle renamed Motilal Oswal Midcap to Most Focused Midcap 30
                # Convert: Motilal Oswal Midcap Fund Direct Plan Growth Option
                # To: motilal-oswal-most-focused-midcap-30-fund-direct-growth
                'pattern': r'Motilal Oswal Midcap Fund[-\s]+(.+?)[-\s]+Plan[-\s]+(.+?)[-\s]+Option',
                'replacement': r'motilal-oswal-most-focused-midcap-30-fund-\1-\2',
                'post_process': True
            },
            {
                # Handle simpler case without "Option"
                'pattern': r'Motilal Oswal Midcap Fund[-\s]+(.+?)[-\s]+Plan[-\s]+(.+)',
                'replacement': r'motilal-oswal-most-focused-midcap-30-fund-\1-\2',
                'post_process': True
            },
            {
                # Handle renamed Motilal Oswal Midcap to Most Focused Midcap 30
                'pattern': r'Motilal Oswal Midcap Fund',
                'replacement': r'motilal-oswal-most-focused-midcap-30-fund',
                'post_process': True
            }
        ],
        'Zerodha': [
            {
                # Handle Zerodha funds with Direct Plan Growth Option
                'pattern': r'Zerodha (.+?)[-\s]+Direct[-\s]+Plan[-\s]+Growth[-\s]+option',
                'replacement': r'zerodha-\1-direct-growth',
                'post_process': True
            },
            {
                # Handle Zerodha funds with Direct Growth
                'pattern': r'Zerodha (.+?)[-\s]+Direct[-\s]+Growth',
                'replacement': r'zerodha-\1-direct-growth',
                'post_process': True
            },
            {
                # Zerodha funds with special naming - also fix LargeMidcap
                'pattern': r'Zerodha (.+)',
                'replacement': r'zerodha-\1',
                'post_process': True
            }
        ],
        'Axis': [
            {
                # Handle Axis ELSS Tax Saver funds
                'pattern': r'Axis ELSS Tax Saver[-\s]+Fund[-\s]+(.+?)[-\s]+option',
                'replacement': r'axis-elss-tax-saver-\1',
                'post_process': True
            },
            {
                # Handle Axis ELSS Tax Saver funds without option
                'pattern': r'Axis ELSS Tax Saver[-\s]+Fund[-\s]+(.+)',
                'replacement': r'axis-elss-tax-saver-\1',
                'post_process': True
            },
            {
                # Handle Axis funds with Direct Plan Growth
                'pattern': r'Axis (.+?)[-\s]+Direct[-\s]+Plan[-\s]+Growth',
                'replacement': r'axis-\1-direct-growth',
                'post_process': True
            },
            {
                # Handle Axis funds with Direct Growth
                'pattern': r'Axis (.+?)[-\s]+Direct[-\s]+Growth',
                'replacement': r'axis-\1-direct-growth',
                'post_process': True
            }
        ]
    }
    
    # Try multiple search strategies
    search_queries = [fund_name]
    
    # Add old name if this is a renamed fund
    for new_name, old_name in renamed_funds.items():
        if fund_name.lower() == new_name.lower():
            search_queries.append(old_name)
            logger.info(f"Will also search with old name: {old_name}")
        elif fund_name.lower() == old_name.lower():
            search_queries.append(new_name)
            logger.info(f"Will also search with new name: {new_name}")
    
    # If ISIN is available, try searching with it first (more precise)
    if isin:
        search_queries.insert(0, isin)
    
    # Groww's internal search API
    search_url = "https://groww.in/v1/api/search/v1/entity"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    for query in search_queries:
        try:
            params = {
                "q": query,
                "limit": 5,  # Get a few results to find the right one
                "vertical": "mutual_fund"  # Restrict to mutual funds
            }
            
            response = requests.get(search_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('content'):
                # Look for exact match or closest match
                for item in data['content']:
                    if item.get('vertical') == 'mutual_fund':
                        # Check if this is our fund
                        if _is_matching_fund(item, fund_name, isin):
                            slug = item.get('page_url')
                            if slug:
                                url = f"https://groww.in/mutual-funds/{slug}"
                                # Cache for 7 days
                                cache.set(cache_key, url, 604800)
                                return url
                
                # If no exact match, try first result
                if data['content']:
                    first_item = data['content'][0]
                    if first_item.get('vertical') == 'mutual_fund':
                        slug = first_item.get('page_url')
                        if slug:
                            url = f"https://groww.in/mutual-funds/{slug}"
                            logger.info(f"Using first match for {fund_name}: {slug}")
                            # Cache for 7 days
                            cache.set(cache_key, url, 604800)
                            return url
                            
        except requests.RequestException as e:
            logger.warning(f"Groww search failed for query '{query}': {e}")
            continue
        except (ValueError, KeyError) as e:
            logger.warning(f"Error parsing Groww response for '{query}': {e}")
            continue
    
    # Fallback to slugified URL (might not work for renamed funds)
    import re
    fallback_slug = fund_name.lower()
    
    # Apply special URL patterns for certain AMCs
    for amc, patterns in url_patterns.items():
        if amc.lower() in fund_name.lower():
            logger.info(f"Checking patterns for {amc} in fund: {fund_name}")
            for pattern_info in patterns:
                pattern = pattern_info['pattern']
                replacement = pattern_info['replacement']
                logger.info(f"Trying pattern: {pattern}")
                if re.match(pattern, fund_name, flags=re.IGNORECASE):
                    fallback_slug = re.sub(pattern, replacement, fund_name, flags=re.IGNORECASE).lower()
                    logger.info(f"Pattern matched! Before post-processing: {fallback_slug}")
                    
                    # Apply post-processing if needed
                    if pattern_info.get('post_process'):
                        # Special handling for Zerodha LargeMidcap
                        if amc.lower() == 'zerodha':
                            fallback_slug = fallback_slug.replace('largemidcap', 'large-midcap')
                        
                        # Replace spaces and special chars with single hyphen
                        fallback_slug = re.sub(r'[\s\.&(),/]+', '-', fallback_slug)
                        # Remove multiple consecutive hyphens
                        fallback_slug = re.sub(r'-+', '-', fallback_slug)
                        # Remove trailing hyphen
                        fallback_slug = fallback_slug.rstrip('-')
                        logger.info(f"After post-processing: {fallback_slug}")
                    
                    break
            else:
                continue  # No pattern matched, try next AMC
            break  # Pattern matched, exit loop
    else:
        # Default slugification if no pattern matched
        # Replace spaces and special chars with single hyphen
        fallback_slug = re.sub(r'[\s\.&(),/]+', '-', fallback_slug)
        
        # Remove multiple consecutive hyphens
        fallback_slug = re.sub(r'-+', '-', fallback_slug)
        
        # Remove trailing hyphen
        fallback_slug = fallback_slug.rstrip('-')
    
    fallback_url = f"https://groww.in/mutual-funds/{fallback_slug}"
    logger.warning(f"Using fallback URL for {fund_name}: {fallback_url}")
    
    # Cache fallback for shorter time
    cache.set(cache_key, fallback_url, 86400)  # 1 day
    
    return fallback_url


def _is_matching_fund(item, fund_name, isin=None):
    """Check if a search result matches our fund"""
    item_name = item.get('name', '').lower()
    fund_name_lower = fund_name.lower()
    
    # Check for name similarity
    # Remove common suffixes for comparison
    suffixes = ['direct growth', 'direct plan', 'growth plan', 'regular growth', 'regular plan']
    
    clean_item_name = item_name
    clean_fund_name = fund_name_lower
    
    for suffix in suffixes:
        clean_item_name = clean_item_name.replace(suffix, '').strip()
        clean_fund_name = clean_fund_name.replace(suffix, '').strip()
    
    # Check for exact match
    if clean_item_name == clean_fund_name or clean_fund_name in clean_item_name:
        return True
    
    # Special case mappings for renamed funds
    renamed_funds = {
        'sbi small cap': 'sbi small midcap',
        'sbi small cap fund': 'sbi small midcap fund',
        'sbi small cap fund direct': 'sbi small midcap fund direct',
        'motilal oswal midcap': 'motilal oswal most focused midcap 30',
        'motilal oswal midcap fund': 'motilal oswal most focused midcap 30 fund',
        'axis midcap': 'axis midcap fund',
        'axis long term equity': 'axis equity fund',
        # Add more mappings as needed
    }
    
    # Check if this is a renamed fund
    for old_name, new_name in renamed_funds.items():
        if old_name in clean_fund_name and new_name in clean_item_name:
            logger.info(f"Detected renamed fund: {old_name} -> {new_name}")
            return True
        if new_name in clean_fund_name and old_name in clean_item_name:
            logger.info(f"Detected renamed fund: {new_name} -> {old_name}")
            return True
    
    # Fuzzy matching for partial names
    fund_words = set(clean_fund_name.split())
    item_words = set(clean_item_name.split())
    
    # If at least 70% of words match and includes AMC name
    if fund_words and item_words:
        common_words = fund_words & item_words
        similarity = len(common_words) / max(len(fund_words), len(item_words))
        
        # Check for AMC name match (important for distinguishing funds)
        amc_names = ['sbi', 'icici', 'hdfc', 'axis', 'kotak', 'reliance', 'birla', 'franklin', 'dsp', 'tata', 'uti', 'nippon', 'idfc', 'bandhan', 'mahindra']
        
        has_amc_match = any(word in amc_names for word in common_words)
        
        if similarity > 0.7 and has_amc_match:
            logger.info(f"Fuzzy match detected: {fund_name} -> {item_name}")
            return True
    
    # If ISIN is available, check that too
    if isin and item.get('isin'):
        return item.get('isin') == isin
    
    return False


def get_groww_url_simple(fund_name):
    """
    Simple version that just slugifies the name
    Use as fallback when search API fails
    """
    import re
    
    # Basic slugification with proper handling of multiple hyphens
    slug = fund_name.lower()
    
    # Replace spaces and special chars with single hyphen
    slug = re.sub(r'[\s\.&(),/]+', '-', slug)
    
    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    
    # Remove trailing hyphen
    slug = slug.rstrip('-')
    
    return f"https://groww.in/mutual-funds/{slug}"
