from django.core.management.base import BaseCommand
from django.db import transaction
from factsheets.fetcher import fetch_factsheet_for_fund, run_monthly_factsheet_refresh
from funds.models import MutualFund
from portfolio.models import PortfolioFund
from datetime import date
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Refresh fund factsheets using enriched data from Captnemo API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scheme-code',
            type=int,
            help='Refresh factsheet for specific fund by scheme code',
        )
        parser.add_argument(
            '--isin',
            type=str,
            help='Refresh factsheet for specific fund by ISIN',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Refresh all funds (not just portfolio funds)',
        )
        parser.add_argument(
            '--use-old-fetcher',
            action='store_true',
            help='Use the old AMFI-based fetcher instead of enriched data',
        )
        parser.add_argument(
            '--skip-enrich',
            action='store_true',
            help='Skip enrichment step (use existing enriched data only)',
        )

    def handle(self, *args, **options):
        scheme_code = options.get('scheme_code')
        isin = options.get('isin')
        all_funds = options.get('all', False)
        use_old_fetcher = options.get('use_old_fetcher', False)
        skip_enrich = options.get('skip_enrich', False)
        
        fetcher_name = "mfapi" if use_old_fetcher else "enriched"
        
        self.stdout.write(self.style.SUCCESS(f'Starting factsheet refresh using {fetcher_name} fetcher...'))

        if scheme_code or isin:
            # Refresh specific fund
            try:
                if scheme_code:
                    fund = MutualFund.objects.get(scheme_code=scheme_code, is_active=True)
                else:
                    fund = MutualFund.objects.get(isin=isin, is_active=True)
                
                self.stdout.write(f"Refreshing factsheet for: {fund.scheme_name}")
                
                factsheet = fetch_factsheet_for_fund(fund, fetcher_name=fetcher_name)
                
                self.stdout.write(self.style.SUCCESS(
                    f"Successfully refreshed factsheet for {fund.scheme_name}\n"
                    f"  Fund Manager: {factsheet.fund_manager}\n"
                    f"  AUM: {factsheet.aum} cr\n"
                    f"  Expense Ratio: {factsheet.expense_ratio}%\n"
                    f"  Holdings: {factsheet.holdings.count()}"
                ))
                
            except MutualFund.DoesNotExist:
                self.stdout.write(self.style.ERROR('Fund not found'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error: {e}'))
                
            return

        # Bulk refresh
        if all_funds:
            # Refresh all active funds
            funds = MutualFund.objects.filter(is_active=True)
            self.stdout.write(f"Refreshing all {funds.count()} active funds...")
        else:
            # Refresh only portfolio funds (default)
            portfolio_fund_ids = PortfolioFund.objects.values_list('fund_id', flat=True).distinct()
            funds = MutualFund.objects.filter(id__in=portfolio_fund_ids, is_active=True)
            self.stdout.write(f"Refreshing {funds.count()} portfolio funds...")

        # Use the bulk refresh function
        with transaction.atomic():
            log = run_monthly_factsheet_refresh(
                fetcher_name=fetcher_name,
                enrich_first=not skip_enrich and fetcher_name == "enriched"
            )

        # Report results
        self.stdout.write(
            self.style.SUCCESS(
                f'\nRefresh complete!\n'
                f'Funds processed: {log.funds_processed}\n'
                f'Errors: {log.errors}\n'
                f'Status: {log.status}'
            )
        )
        
        if log.errors > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'\nCheck FactsheetFetchLog for error details.\n'
                    f'Some funds might not have holdings data available.'
                )
            )
