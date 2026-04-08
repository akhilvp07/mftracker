"""
Kite Connect integration for MF Tracker
"""
import logging
from datetime import date
from django.shortcuts import redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from kiteconnect import KiteConnect

logger = logging.getLogger(__name__)

# Get API credentials from KiteCredentials model
def get_kite_credentials():
    """Get Kite credentials from database"""
    from .models import KiteCredentials
    creds = KiteCredentials.get_active_credentials()
    if creds:
        return creds.api_key, creds.get_api_secret()
    return None, None

KITE_API_KEY, KITE_API_SECRET = get_kite_credentials()


def get_kite_session(request):
    """Get Kite session from user session"""
    return request.session.get('kite_access_token')


def set_kite_session(request, access_token):
    """Store Kite session in user session"""
    request.session['kite_access_token'] = access_token
    request.session.modified = True


def create_kite_instance(access_token=None):
    """Create and return KiteConnect instance"""
    if not KITE_API_KEY:
        raise ValueError("KITE_API_KEY not configured")
    
    kite = KiteConnect(api_key=KITE_API_KEY)
    
    if access_token:
        kite.set_access_token(access_token)
    
    return kite


def initiate_kite_login(request):
    """Redirect user to Kite for authentication"""
    if not KITE_API_KEY:
        logger.error("KITE_API_KEY not configured")
        messages.error(request, 'Kite API not configured')
        return redirect('dashboard')
    
    # Check if user is authenticated
    if not request.user.is_authenticated:
        # Store intended URL and redirect to login
        messages.info(request, 'Please login to connect your Kite account.')
        return redirect(f'/accounts/login/?next={request.path}')
    
    kite = create_kite_instance()
    login_url = kite.login_url()
    return redirect(login_url)


@login_required
def kite_callback(request):
    """Handle callback from Kite after authentication"""
    request_token = request.GET.get('request_token')
    status = request.GET.get('status')
    
    if status == 'error' or not request_token:
        error_msg = request.GET.get('message', 'Authentication failed')
        messages.error(request, f'Kite authentication failed: {error_msg}')
        return redirect('dashboard')
    
    try:
        # Create Kite instance
        kite = create_kite_instance()
        
        # Exchange request_token for access_token
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        
        # Store access token
        access_token = data["access_token"]
        set_kite_session(request, access_token)
        
        # Store user info
        request.session['kite_user_id'] = data.get('user_id')
        request.session['kite_user_name'] = data.get('user_name')
        
        logger.info(f"Successfully authenticated Kite user: {data.get('user_name')}")
        messages.success(request, 'Kite authentication successful!')
        
        # Fetch holdings after successful login
        try:
            fetch_and_sync_holdings(request)
            messages.success(request, 'Your mutual fund holdings have been synced from Kite!')
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            messages.warning(request, 'Authentication successful, but couldn\'t fetch holdings.')
        
        return redirect('dashboard')
        
    except Exception as e:
        logger.error(f"Error exchanging Kite token: {e}")
        messages.error(request, f'Error completing Kite authentication: {str(e)}')
        return redirect('dashboard')


def fetch_and_sync_holdings(request):
    """Fetch mutual fund holdings from Kite and sync with local database"""
    access_token = get_kite_session(request)
    if not access_token:
        raise ValueError("No Kite session found")
    
    kite = create_kite_instance(access_token)
    
    # Fetch holdings
    holdings = kite.mf_holdings()
    
    if not holdings:
        logger.info("No mutual fund holdings found in Kite")
        return
    
    # Sync with local database
    from funds.models import MutualFund
    from funds.services import fetch_fund_nav
    from portfolio.models import Portfolio, PortfolioFund, PurchaseLot
    from factsheets.fetcher import _fetch_fund_manager_from_amfi_scheme_page
    
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user)
    
    for holding in holdings:
        # Find the fund by ISIN (tradingsymbol in Kite)
        isin = holding.get('tradingsymbol')
        fund_name = holding.get('fund')
        
        # Try to find fund by ISIN first
        fund = None
        if isin:
            try:
                fund = MutualFund.objects.get(isin=isin)
            except MutualFund.DoesNotExist:
                # Try to find by name
                try:
                    fund = MutualFund.objects.get(scheme_name__icontains=fund_name.split(' - ')[0])
                except MutualFund.DoesNotExist:
                    logger.warning(f"Fund not found: {fund_name} (ISIN: {isin})")
                    continue
        
        if not fund:
            logger.warning(f"Could not find fund: {fund_name}")
            continue
        
        # Fetch current NAV if not available or outdated
        # Also check if Kite provides last_price which might be more recent
        kite_last_price = holding.get('last_price')
        if kite_last_price and float(kite_last_price) > 0:
            # Use Kite's last_price if available
            if not fund.current_nav or abs(float(kite_last_price) - float(fund.current_nav)) > 0.01:
                fund.current_nav = float(kite_last_price)
                fund.nav_date = date.today()
                fund.save()
                logger.info(f"Updated NAV from Kite for {fund.scheme_name}: ₹{kite_last_price}")
        elif not fund.current_nav or not fund.nav_date or fund.nav_date < date.today():
            # Fetch from AMFI/mfapi if Kite doesn't provide or NAV is outdated
            try:
                nav_data = fetch_fund_nav(fund.scheme_code)
                if nav_data:
                    fund.current_nav = nav_data['nav']
                    fund.nav_date = nav_data['date']
                    fund.save()
                    logger.info(f"Updated NAV from API for {fund.scheme_name}: ₹{nav_data['nav']}")
            except Exception as e:
                logger.error(f"Error fetching NAV for {fund.scheme_name}: {e}")
        
        # Also fetch fund manager if not available
        if not fund.fund_manager:
            try:
                manager = _fetch_fund_manager_from_amfi_scheme_page(fund)
                if manager:
                    fund.fund_manager = manager
                    fund.save(update_fields=['fund_manager'])
                    logger.info(f"Updated fund manager for {fund.scheme_name}: {manager}")
            except Exception as e:
                logger.error(f"Error fetching fund manager for {fund.scheme_name}: {e}")
        
        # Create or update portfolio fund
        pf, created = PortfolioFund.objects.get_or_create(
            portfolio=portfolio,
            fund=fund
        )
        
        if created:
            logger.info(f"Added fund to portfolio: {fund.scheme_name}")
        
        # Create/update purchase lot
        quantity = float(holding.get('quantity', 0))
        avg_price = float(holding.get('average_price', 0))
        
        if quantity > 0:
            # Check if a lot from Kite already exists
            existing_lot = pf.lots.filter(notes__startswith='Kite:').first()
            
            if existing_lot:
                # Update existing lot
                existing_lot.units = quantity
                existing_lot.avg_nav = avg_price
                existing_lot.notes = f"Kite: Folio {holding.get('folio', '')}"
                existing_lot.save()
            else:
                # Create new lot
                PurchaseLot.objects.create(
                    portfolio_fund=pf,
                    units=quantity,
                    avg_nav=avg_price,
                    purchase_date=date.today(),  # Use today's date as default
                    notes=f"Kite: Folio {holding.get('folio', '')}"
                )
    
    logger.info(f"Synced {len(holdings)} holdings from Kite")


def get_kite_holdings(request):
    """Get Kite holdings (returns raw data)"""
    access_token = get_kite_session(request)
    if not access_token:
        return None
    
    kite = create_kite_instance(access_token)
    return kite.mf_holdings()


def kite_postback(request):
    """Handle postbacks from Kite (order updates, etc.)"""
    if request.method == 'POST':
        logger.info(f"Received Kite postback: {request.body}")
        # TODO: Process postback data and update database
    
    return HttpResponse(status=200)
