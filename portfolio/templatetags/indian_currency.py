"""
Template tags for Indian number formatting
"""
from django import template

register = template.Library()


@register.filter
def indian_currency(number):
    """
    Format number in Indian currency format (lakhs/crores)
    Example: 2121096 -> 21,21,096
    """
    try:
        # Convert to string and handle decimal
        s = str(float(number))
        
        # Split into integer and decimal parts
        if '.' in s:
            integer_part, decimal_part = s.split('.')
        else:
            integer_part, decimal_part = s, ''
        
        # Remove negative sign for formatting
        is_negative = integer_part.startswith('-')
        if is_negative:
            integer_part = integer_part[1:]
        
        # Remove leading zeros
        integer_part = integer_part.lstrip('0') or '0'
        
        # Format based on length
        if len(integer_part) <= 3:
            formatted = integer_part
        elif len(integer_part) <= 5:
            # For thousands: 1,234
            formatted = f"{integer_part[:-3]},{integer_part[-3:]}"
        else:
            # For lakhs and above: 21,21,096
            # First part: everything except last 3 digits
            first_part = integer_part[:-3]
            # Insert commas after every 2 digits from right
            first_parts = []
            while first_part:
                first_parts.append(first_part[-2:])
                first_part = first_part[:-2]
            first_parts.reverse()
            formatted_first = ','.join(first_parts)
            formatted = f"{formatted_first},{integer_part[-3:]}"
        
        # Add back negative sign
        if is_negative:
            formatted = f"-{formatted}"
        
        # Add decimal part if exists
        if decimal_part:
            formatted = f"{formatted}.{decimal_part}"
        
        return formatted
    except (ValueError, TypeError):
        return number


@register.filter
def indian_currency_int(number):
    """
    Format integer in Indian currency format without decimal places
    """
    try:
        # Round to nearest integer first
        rounded = round(float(number))
        return indian_currency(int(rounded))
    except (ValueError, TypeError):
        return number
