#!/bin/bash
# Build script for Vercel deployment

# Collect static files
python manage.py collectstatic --noinput

echo "Build completed successfully"
