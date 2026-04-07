from django.core.management.base import BaseCommand
from funds.models import MutualFund
from factsheets.groww_utils import get_groww_url
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cache Groww URLs for all mutual funds'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Number of funds to process (default: 100)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing cache first',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        clear_cache = options['clear']
        
        if clear_cache:
            from django.core.cache import cache
            cache.clear()
            self.stdout.write("Cleared all cache")
        
        # Get funds that are in portfolios
        funds = MutualFund.objects.filter(portfolio_entries__isnull=False).distinct()[:limit]
        
        self.stdout.write(f"Caching Groww URLs for {funds.count()} funds...")
        
        success = 0
        failed = 0
        
        for fund in funds:
            try:
                url = get_groww_url(fund.scheme_name, fund.isin)
                if url and url != "#":
                    success += 1
                    self.stdout.write(f"✓ {fund.scheme_name[:50]:<50} -> {url.split('/')[-1]}")
                else:
                    failed += 1
                    self.stdout.write(f"✗ {fund.scheme_name[:50]:<50} -> NOT FOUND")
            except Exception as e:
                failed += 1
                self.stdout.write(f"✗ {fund.scheme_name[:50]:<50} -> ERROR: {e}")
        
        self.stdout.write(f"\nDone! Success: {success}, Failed: {failed}")
