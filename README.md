# MFTracker — Mutual Fund Investment Tracker

A production-ready Django application for tracking mutual fund investments with XIRR calculation, portfolio rebalancing, factsheet comparison, and smart alerts.

## Features

- **Portfolio Dashboard** — Real-time NAV, invested value, gains, and XIRR per fund and overall
- **Portfolio Rebalancing** — Smart asset allocation rebalancing with Large/Mid/Small cap targets
- **XIRR Calculation** — Newton-Raphson via scipy, supporting multiple purchase lots per fund
- **Factsheet Comparison** — Month-over-month diff: new/exited holdings, weight changes, sector shifts
- **Smart Alerts** — Fund manager change, category change, objective change — persisted in DB, optional email
- **Dark/Light Mode** — Toggle via navbar button, persisted in localStorage
- **Scheduled Jobs** — Daily NAV refresh at 9 AM IST, monthly factsheet refresh on 1st of month
- **Zerodha Kite** — Optional OAuth portfolio import (app works fully without it)
- **Asset Allocation** — Set targets for Equity/Debt/Gold and Equity cap distribution (Large/Mid/Small)

---

## WSL / Local Setup

### Prerequisites

```bash
# WSL Ubuntu — ensure Python 3.10+ is installed
python3 --version

# Install pip if missing
sudo apt install python3-pip python3-venv -y
```

### Quick Start

```bash
# Clone / extract the project
cd mftracker

# Run the setup script (creates venv, migrates, seeds funds, creates superuser)
bash setup_dev.sh

# Start the server
source venv/bin/activate
python manage.py runserver
```

Open http://localhost:8000 and log in with your superuser credentials.

### Manual Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Edit .env with your settings
python manage.py migrate
python manage.py seed_funds   # Seeds ~10,000 funds from mfapi.in (takes ~30s)
python manage.py createsuperuser
python manage.py runserver
```

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | *(required)* | Random secret key for Django |
| `DJANGO_DEBUG` | `True` | Set to `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `EMAIL_HOST` | `smtp.gmail.com` | SMTP server |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_USE_TLS` | `True` | Use TLS |
| `EMAIL_HOST_USER` | *(empty)* | Gmail address |
| `EMAIL_HOST_PASSWORD` | *(empty)* | Gmail App Password |
| `DEFAULT_FROM_EMAIL` | *(empty)* | From address for alerts |
| `KITE_API_KEY` | *(empty)* | Zerodha Kite API key (optional) |
| `KITE_API_SECRET` | *(empty)* | Zerodha Kite API secret (optional) |
| `KITE_REDIRECT_URL` | `http://localhost:8000/...` | Kite OAuth callback URL |
| `WEIGHT_CHANGE_THRESHOLD` | `1.0` | Minimum % for weight change alerts |
| `FACTSHEET_REFRESH_DAY` | `1` | Day of month for factsheet refresh |
| `FACTSHEET_REFRESH_HOUR` | `2` | Hour (24h) for factsheet refresh |
| `NAV_REFRESH_HOUR` | `9` | Hour (24h) for daily NAV refresh |

### Gmail App Password Setup

1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account → Security → App passwords
3. Generate a password for "Mail"
4. Use that password as `EMAIL_HOST_PASSWORD`

If email is not configured, all alerts are stored in-app and shown as a notification badge.

---

## Management Commands

```bash
# Seed/re-seed fund database from mfapi.in (Direct Plan Growth only)
python manage.py seed_funds
python manage.py seed_funds --force  # Force re-seed

# Refresh NAV for all tracked funds
python manage.py refresh_navs

# Run monthly factsheet refresh manually
python manage.py refresh_factsheets

# Cache Groww URLs for all funds (optional, improves performance)
python manage.py cache_groww_urls
```

---

## Production Deployment

```bash
# Set environment variables in .env:
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong-random-key>
DJANGO_ALLOWED_HOSTS=yourdomain.com

# Collect static files
python manage.py collectstatic --noinput

# Run with gunicorn
gunicorn config.wsgi:application --workers 4 --bind 0.0.0.0:8000
```

Static files are served via WhiteNoise (no separate nginx needed for small deployments).

---

## Project Structure

```
mftracker/
├── config/              # Django project config (settings, urls, wsgi)
├── funds/               # MutualFund model, NAV fetching, seeding
├── portfolio/           # Portfolio, holdings, lots, XIRR, scheduler
│   ├── services/        # Rebalancing logic and calculations
│   └── migrations/      # Database migrations
├── alerts/              # Alert model, email/in-app notifications
├── factsheets/          # Factsheet fetcher, diff engine
│   ├── management/      # Management commands
│   └── templatetags/     # Template tags for Groww URLs
├── templates/           # Django HTML templates
├── static/              # CSS, JS
├── .env.example         # Environment variable template
├── requirements.txt
├── Procfile
├── KITE_API_SETUP.md    # Kite Connect API documentation
└── README.md
```

---

## Data Sources

| Source | Usage |
|---|---|
| `mfapi.in` | Fund list seeding, current NAV, NAV history |
| AMFI India | Factsheet data (holdings, sectors) — pluggable fetcher |
| Zerodha Kite | Optional portfolio import via OAuth |

Factsheet fetcher is designed as a pluggable registry — swap data sources by adding a new `FactsheetFetcher` subclass in `factsheets/fetcher.py` and registering it in `_FETCHER_REGISTRY`.

---

## Default Credentials (dev only)

After running `setup_dev.sh` or `createsuperuser`, use your chosen credentials.  
The setup script creates a default admin user — **change the password in production**.
# Deployment trigger
# Styling restored - reverted static caching changes
# Fri Apr 10 18:12:11 IST 2026
