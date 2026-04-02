from django.core.management.base import BaseCommand
from factsheets.fetcher import run_monthly_factsheet_refresh


class Command(BaseCommand):
    help = 'Run monthly factsheet refresh for all portfolio funds'

    def handle(self, *args, **options):
        self.stdout.write('Running factsheet refresh...')
        log = run_monthly_factsheet_refresh()
        self.stdout.write(self.style.SUCCESS(
            f'Done: {log.funds_processed} processed, {log.errors} errors'
        ))
