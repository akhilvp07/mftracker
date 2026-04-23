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
        s = str(number)
        
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


@register.filter
def div(number, divisor):
    """
    Divide number by divisor
    """
    try:
        return float(number) / float(divisor)
    except (ValueError, TypeError, ZeroDivisionError):
        return number


@register.filter
def round_half_down(number, decimals=2):
    """
    Round number to specified decimal places using round half down.
    If the decimal at position (decimals + 1) is > 5, round up.
    If it's <= 5, truncate (keep the same value).
    Returns a string with the exact number of decimal places.
    """
    try:
        num = float(number)
        multiplier = 10 ** decimals
        # Multiply to shift decimal point
        shifted = num * multiplier
        # Get the decimal at position (decimals + 1) by looking at the first decimal of shifted
        # For example: 259.3759456 with decimals=2 -> shifted=25937.59456
        # We need to look at the first decimal (5) after the decimal point
        fractional = shifted - int(shifted)
        # Multiply by 10 to get the first decimal digit
        next_digit = int(fractional * 10)
        # If the next digit > 5, round up, otherwise truncate
        if next_digit > 5:
            result = int(shifted + 1) / multiplier
        else:
            result = int(shifted) / multiplier
        # Format as string with exact decimal places
        return f"{result:.{decimals}f}"
    except (ValueError, TypeError):
        return number
