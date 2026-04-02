from django.core.management.base import BaseCommand
from funds.services import seed_fund_database


class Command(BaseCommand):
    help = 'Seed the fund database from mfapi.in'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-seed even if already done')

    def handle(self, *args, **options):
        self.stdout.write('Seeding fund database from mfapi.in...')
        try:
            status = seed_fund_database(force=options['force'])
            self.stdout.write(self.style.SUCCESS(
                f'Done! {status.total_funds} funds seeded.'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Seeding failed: {e}'))
