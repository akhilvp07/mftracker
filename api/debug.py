#!/usr/bin/env python
import os
import sys

def handler(request):
    """Debug environment variables"""
    db_url = os.environ.get('DATABASE_URL', 'NOT SET')
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/plain'},
        'body': f'DATABASE_URL: {db_url[:50]}...' if db_url != 'NOT SET' else 'DATABASE_URL: NOT SET'
    }
