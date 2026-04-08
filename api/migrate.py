#!/usr/bin/env python
import os
import sys
import django

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Setup Django
django.setup()

# Run migrations
from django.core.management import execute_from_command_line

def handler(request):
    """Run migrations on first request"""
    try:
        execute_from_command_line(['manage.py', 'migrate', '--noinput'])
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'Migrations completed successfully!'
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/plain'},
            'body': f'Migration error: {str(e)}'
        }

# For Vercel
app = handler

# For direct execution
if __name__ == '__main__':
    execute_from_command_line(['manage.py', 'migrate', '--noinput'])
