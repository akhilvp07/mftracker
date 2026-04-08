#!/usr/bin/env python
import os
import sys

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

# Import and run migrations
from django.core.management import execute_from_command_line

# For Vercel
def handler(request):
    """Run migrations"""
    try:
        execute_from_command_line(['manage.py', 'migrate', '--noinput'])
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/html'},
            'body': '''
            <html>
                <body style="font-family: Arial; padding: 20px;">
                    <h1>✅ Migrations completed successfully!</h1>
                    <p><a href="/">Go to your app</a></p>
                </body>
            </html>
            '''
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html'},
            'body': f'<h1>Error: {str(e)}</h1>'
        }

# Also export as app for Vercel
app = handler

if __name__ == '__main__':
    execute_from_command_line(['manage.py', 'migrate', '--noinput'])
