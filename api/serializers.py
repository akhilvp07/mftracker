from rest_framework import serializers
from portfolio.models import Portfolio, PortfolioFund, PurchaseLot
from funds.models import MutualFund


class MutualFundSerializer(serializers.ModelSerializer):
    """Serializer for MutualFund model"""
    class Meta:
        model = MutualFund
        fields = [
            'id', 'scheme_code', 'scheme_name', 'isin', 'amc', 'category',
            'fund_type', 'fund_category', 'plan', 'fund_manager',
            'investment_objective', 'crisil_rating', 'current_nav', 'nav_date',
            'nav_last_updated', 'expense_ratio', 'aum', 'face_value',
            'day_change', 'day_change_pct', 'morningstar_rating',
            'return_1m', 'return_3m', 'return_6m', 'return_1y', 'return_3y',
            'return_5y', 'return_since_inception'
        ]


class PurchaseLotSerializer(serializers.ModelSerializer):
    """Serializer for PurchaseLot model"""
    class Meta:
        model = PurchaseLot
        fields = ['id', 'units', 'avg_nav', 'purchase_date', 'transaction_type']


class PortfolioFundSerializer(serializers.ModelSerializer):
    """Serializer for PortfolioFund model"""
    fund = MutualFundSerializer(read_only=True)
    fund_name = serializers.CharField(source='fund.scheme_name', read_only=True)
    scheme_code = serializers.IntegerField(source='fund.scheme_code', read_only=True)
    
    class Meta:
        model = PortfolioFund
        fields = [
            'id', 'fund', 'fund_name', 'scheme_code', 'notes', 'created_at'
        ]


class DashboardHoldingSerializer(serializers.ModelSerializer):
    """Serializer for dashboard holdings with calculated fields"""
    fund_name = serializers.CharField(source='fund.scheme_name', read_only=True)
    scheme_code = serializers.IntegerField(source='fund.scheme_code', read_only=True)
    invested = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()
    gain = serializers.SerializerMethodField()
    gain_pct = serializers.SerializerMethodField()
    xirr = serializers.SerializerMethodField()
    
    class Meta:
        model = PortfolioFund
        fields = [
            'id', 'fund_name', 'scheme_code', 'invested', 'current',
            'gain', 'gain_pct', 'xirr'
        ]
    
    def get_invested(self, obj):
        return float(obj.total_invested) if obj.total_invested else 0
    
    def get_current(self, obj):
        return float(obj.current_value) if obj.current_value else 0
    
    def get_gain(self, obj):
        return float(obj.absolute_gain) if obj.absolute_gain else 0
    
    def get_gain_pct(self, obj):
        cost_basis = obj.total_cost_basis or 0
        gain = obj.absolute_gain or 0
        return float(gain / cost_basis * 100) if cost_basis > 0 else 0
    
    def get_xirr(self, obj):
        from portfolio.xirr import calculate_fund_xirr
        try:
            xirr = calculate_fund_xirr(obj)
            return float(xirr) if xirr is not None else None
        except:
            return None


class DashboardSerializer(serializers.Serializer):
    """Serializer for dashboard aggregated data"""
    total_invested = serializers.FloatField()
    total_current = serializers.FloatField()
    total_gain = serializers.FloatField()
    total_gain_pct = serializers.FloatField()
    portfolio_xirr = serializers.FloatField(allow_null=True)
    holdings = DashboardHoldingSerializer(many=True)
