from django.core.management.base import BaseCommand
from funds.services import refresh_all_navs


class Command(BaseCommand):
    help = 'Refresh NAV for all active funds'

    def handle(self, *args, **options):
        self.stdout.write('Refreshing NAVs...')
        success, errors = refresh_all_navs()
        self.stdout.write(self.style.SUCCESS(f'Done: {success} ok, {errors} errors'))
