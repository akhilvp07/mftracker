#!/bin/bash
set -e
echo "=== MFTracker Dev Setup ==="

# Create and activate virtualenv
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install -r requirements.txt

# Copy env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit it before running"
fi

# Run migrations
python manage.py migrate

# Seed fund database
python manage.py seed_funds

# Create superuser interactively
python manage.py createsuperuser

echo ""
echo "=== Setup complete! Run: source venv/bin/activate && python manage.py runserver ==="
