from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from funds.models import MutualFund
from .models import Portfolio, PortfolioFund, PurchaseLot


class NetInvestmentGainCalculationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass123')
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.fund = MutualFund.objects.create(
            scheme_code=123456,
            scheme_name='Test Fund',
            current_nav=Decimal('25.0000'),
        )

    def test_absolute_gain_cost_basis_uses_current_value_minus_net_investment(self):
        pf = PortfolioFund.objects.create(portfolio=self.portfolio, fund=self.fund)

        PurchaseLot.objects.create(
            portfolio_fund=pf,
            units=Decimal('100.000'),
            avg_nav=Decimal('10.0000'),
            purchase_date=date(2024, 1, 1),
        )
        PurchaseLot.objects.create(
            portfolio_fund=pf,
            units=Decimal('100.000'),
            avg_nav=Decimal('20.0000'),
            purchase_date=date(2024, 2, 1),
        )
        PurchaseLot.objects.create(
            portfolio_fund=pf,
            units=Decimal('-50.000'),
            avg_nav=Decimal('15.0000'),
            purchase_date=date(2024, 3, 1),
        )

        self.assertEqual(pf.current_value, Decimal('3750.0000'))
        self.assertEqual(pf.total_invested, Decimal('2250.0000'))
        self.assertEqual(pf.absolute_gain_cost_basis, pf.current_value - pf.total_invested)

    def test_absolute_gain_cost_basis_returns_zero_when_nav_is_missing(self):
        pf = PortfolioFund.objects.create(portfolio=self.portfolio, fund=self.fund)
        PurchaseLot.objects.create(
            portfolio_fund=pf,
            units=Decimal('100.000'),
            avg_nav=Decimal('10.0000'),
            purchase_date=date(2024, 1, 1),
        )

        self.fund.current_nav = None
        self.fund.save(update_fields=['current_nav'])

        self.assertEqual(pf.absolute_gain_cost_basis, Decimal('0'))
