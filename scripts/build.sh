#!/bin/bash
set -e

echo "Starting build process..."

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run migrations if DATABASE_URL is set
if [ -n "$DATABASE_URL" ]; then
    echo "Running database migrations..."
    python manage.py migrate --noinput --fake-initial
else
    echo "WARNING: DATABASE_URL not set, skipping migrations"
fi

echo "Build completed successfully!"
