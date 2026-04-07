import os
import sys
from django.core.wsgi import get_wsgi_application

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Get the WSGI application
django_app = get_wsgi_application()

# Vercel serverless handler
def handler(request):
    """
    This is the main entry point for Vercel serverless functions.
    It converts Vercel's request format to WSGI format.
    """
    # Convert Vercel request to WSGI environ
    environ = {
        'REQUEST_METHOD': request.get('method', 'GET'),
        'PATH_INFO': request.get('path', '/'),
        'QUERY_STRING': request.get('query', ''),
        'SERVER_NAME': 'vercel.app',
        'SERVER_PORT': '443',
        'HTTP_HOST': request.get('headers', {}).get('host', 'vercel.app'),
        'HTTP_COOKIE': '; '.join([f"{k}={v}" for k, v in request.get('cookies', {}).items()]),
        'wsgi.url_scheme': 'https',
        'wsgi.input': request.get('body', ''),
        'wsgi.errors': sys.stderr,
        'wsgi.version': (1, 0),
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }
    
    # Add headers
    for key, value in request.get('headers', {}).items():
        key = key.upper().replace('-', '_')
        if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            environ[f'HTTP_{key}'] = value
        else:
            environ[key] = value
    
    # Start response
    response_data = {}
    def start_response(status, headers, exc_info=None):
        response_data['status'] = status
        response_data['headers'] = headers
    
    # Get response from Django
    response_body = django_app(environ, start_response)
    
    # Convert to Vercel response format
    return {
        'statusCode': int(response_data['status'].split()[0]),
        'headers': dict(response_data['headers']),
        'body': ''.join(response_body),
    }

# For Vercel
app = handler
