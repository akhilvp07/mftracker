from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.cache import cache
from django.utils import timezone
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.db.models import Sum, Q
from decimal import Decimal

from portfolio.models import Portfolio, PortfolioFund
from funds.models import MutualFund
from portfolio.xirr import calculate_portfolio_xirr
from funds.services import fetch_fund_nav
from .serializers import (
    MutualFundSerializer,
    DashboardHoldingSerializer,
    DashboardSerializer
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_api(request):
    """
    GET /api/dashboard/
    Returns aggregated portfolio data for the authenticated user.
    Cached per-user with 5-minute TTL.
    """
    user = request.user
    cache_key = f'dashboard_{user.id}'
    
    # Try to get from cache
    cached_data = cache.get(cache_key)
    if cached_data:
        return Response(cached_data)
    
    # Get or create portfolio
    portfolio, _ = Portfolio.objects.get_or_create(user=user)
    holdings = portfolio.holdings.select_related('fund').prefetch_related('lots').all()
    
    # Calculate totals
    total_invested = Decimal('0')
    total_current = Decimal('0')
    total_gain = Decimal('0')
    
    holdings_data = []
    for pf in holdings:
        invested = pf.total_invested or Decimal('0')
        current = pf.current_value or Decimal('0')
        gain = pf.absolute_gain or Decimal('0')
        
        total_invested += invested
        total_current += current
        total_gain += gain
        
        # Calculate XIRR for this fund
        try:
            xirr = calculate_fund_xirr(pf)
            xirr_value = float(xirr) if xirr is not None else None
        except:
            xirr_value = None
        
        holdings_data.append({
            'id': pf.id,
            'fund_name': pf.fund.scheme_name,
            'scheme_code': pf.fund.scheme_code,
            'invested': float(invested),
            'current': float(current),
            'gain': float(gain),
            'gain_pct': float((gain / invested * 100) if invested > 0 else 0),
            'xirr': xirr_value
        })
    
    # Calculate portfolio XIRR
    try:
        portfolio_xirr = calculate_portfolio_xirr(portfolio)
        portfolio_xirr_value = float(portfolio_xirr) if portfolio_xirr is not None else None
    except:
        portfolio_xirr_value = None
    
    total_gain_pct = float((total_gain / total_invested * 100) if total_invested > 0 else 0)
    
    response_data = {
        'total_invested': float(total_invested),
        'total_current': float(total_current),
        'total_gain': float(total_gain),
        'total_gain_pct': total_gain_pct,
        'portfolio_xirr': portfolio_xirr_value,
        'holdings': holdings_data
    }
    
    # Cache for 5 minutes (300 seconds)
    cache.set(cache_key, response_data, 300)
    
    return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def funds_list(request):
    """
    GET /api/funds/
    Returns mutual fund list with search and pagination.
    Cached publicly with 1-hour TTL via HTTP headers.
    Query params:
    - search: Search by scheme name or AMC
    - category: Filter by category
    - page: Page number (default: 1)
    - page_size: Items per page (default: 100)
    """
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 100))
    
    queryset = MutualFund.objects.filter(is_active=True)
    
    if search:
        queryset = queryset.filter(
            Q(scheme_name__icontains=search) |
            Q(amc__icontains=search) |
            Q(scheme_code=search)
        )
    
    if category:
        queryset = queryset.filter(category__icontains=category)
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    total = queryset.count()
    funds = queryset[start:end]
    
    serializer = MutualFundSerializer(funds, many=True)
    
    response = Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })
    
    # Add cache headers for 1 hour (3600 seconds)
    response['Cache-Control'] = 'public, max-age=3600'
    
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh_nav_api(request):
    """
    POST /api/refresh-nav/
    Refresh NAV for all funds in the user's portfolio.
    """
    user = request.user
    portfolio, _ = Portfolio.objects.get_or_create(user=user)
    holdings = portfolio.holdings.select_related('fund').all()
    
    refreshed_count = 0
    failed_count = 0
    
    for pf in holdings:
        try:
            fetch_fund_nav(pf.fund, fetch_history=False)
            refreshed_count += 1
        except Exception as e:
            failed_count += 1
    
    # Clear dashboard cache for this user
    cache_key = f'dashboard_{user.id}'
    cache.delete(cache_key)
    
    return Response({
        'success': True,
        'refreshed': refreshed_count,
        'failed': failed_count
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recalc_xirr_api(request):
    """
    POST /api/recalc-xirr/
    Recalculate XIRR for the user's portfolio.
    """
    user = request.user
    portfolio, _ = Portfolio.objects.get_or_create(user=user)
    
    # Clear XIRR cache
    from portfolio.models import XIRRCache
    XIRRCache.objects.filter(portfolio_fund__portfolio=portfolio).delete()
    
    # Clear dashboard cache for this user
    cache_key = f'dashboard_{user.id}'
    cache.delete(cache_key)
    
    return Response({
        'success': True,
        'message': 'XIRR cache cleared. Will be recalculated on next dashboard load.'
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fund_detail(request, scheme_code):
    """
    GET /api/funds/{scheme_code}/
    Get detailed information about a specific fund.
    """
    try:
        fund = MutualFund.objects.get(scheme_code=scheme_code, is_active=True)
        serializer = MutualFundSerializer(fund)
        
        response = Response(serializer.data)
        response['Cache-Control'] = 'public, max-age=3600'
        return response
    except MutualFund.DoesNotExist:
        return Response(
            {'error': 'Fund not found'},
            status=status.HTTP_404_NOT_FOUND
        )
