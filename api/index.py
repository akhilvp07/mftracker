import os
import sys
import io
from django.core.wsgi import get_wsgi_application

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django
import django
django.setup()

# Get the WSGI application
django_app = get_wsgi_application()

# Vercel serverless handler
def handler(request):
    """
    This is the main entry point for Vercel serverless functions.
    It converts Vercel's request format to WSGI format.
    """
    try:
        # Convert Vercel request to WSGI environ
        body = request.get('body', '')
        if isinstance(body, str):
            body_bytes = body.encode('utf-8')
        else:
            body_bytes = body
            
        environ = {
            'REQUEST_METHOD': request.get('method', 'GET'),
            'PATH_INFO': request.get('path', '/'),
            'QUERY_STRING': request.get('query', ''),
            'SERVER_NAME': request.get('headers', {}).get('host', 'vercel.app'),
            'SERVER_PORT': '443',
            'HTTP_HOST': request.get('headers', {}).get('host', 'vercel.app'),
            'wsgi.url_scheme': 'https',
            'wsgi.input': io.BytesIO(body_bytes),
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
        
        # Handle cookies
        cookies = request.get('cookies', {})
        if cookies:
            cookie_header = '; '.join([f"{k}={v}" for k, v in cookies.items()])
            environ['HTTP_COOKIE'] = cookie_header
        
        # Start response
        response_data = {}
        def start_response(status, headers, exc_info=None):
            response_data['status'] = status
            response_data['headers'] = headers
        
        # Get response from Django
        response_body = list(django_app(environ, start_response))
        
        # Convert to Vercel response format
        return {
            'statusCode': int(response_data['status'].split()[0]),
            'headers': dict(response_data['headers']),
            'body': ''.join(response_body),
        }
        
    except Exception as e:
        # Return error response
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/plain'},
            'body': f'Internal Server Error: {str(e)}',
        }

# For Vercel
app = handler
