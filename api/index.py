import os
import sys
from django.core.wsgi import get_wsgi_application
from django.core.management import execute_from_command_line

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Run collectstatic if staticfiles directory doesn't exist
from django.conf import settings
if not os.path.exists(settings.STATIC_ROOT):
    os.makedirs(settings.STATIC_ROOT, exist_ok=True)
    execute_from_command_line(['manage.py', 'collectstatic', '--noinput', '--clear'])

# Get the WSGI application
app = get_wsgi_application()
