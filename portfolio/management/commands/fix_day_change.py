from django.core.management.base import BaseCommand
from django.db import models
from funds.models import MutualFund
from funds.services import calculate_day_change_from_history
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fix day change values for funds with null day_change or day_change_pct'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scheme-code',
            type=str,
            help='Fix only specific scheme code',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        scheme_code = options.get('scheme_code')
        dry_run = options.get('dry_run')

        if scheme_code:
            funds = MutualFund.objects.filter(scheme_code=scheme_code)
        else:
            funds = MutualFund.objects.filter(
                models.Q(day_change__isnull=True) | models.Q(day_change_pct__isnull=True)
            )

        self.stdout.write(f"Found {funds.count()} funds to process")

        for fund in funds:
            change, change_pct = calculate_day_change_from_history(fund)
            
            if change is not None and change_pct is not None:
                self.stdout.write(
                    f"\n{fund.scheme_name} ({fund.scheme_code}):"
                    f"\n  Current: day_change={fund.day_change}, day_change_pct={fund.day_change_pct}"
                    f"\n  Calculated: change={change}, pct={change_pct:.2f}%"
                )
                
                if not dry_run:
                    fund.day_change = change
                    fund.day_change_pct = change_pct
                    fund.save()
                    self.stdout.write(self.style.SUCCESS("  ✓ Updated"))
                else:
                    self.stdout.write("  [DRY RUN] Would update")
            else:
                self.stdout.write(
                    f"\n{fund.scheme_name} ({fund.scheme_code}): "
                    "Could not calculate day change (no history)"
                )

        if dry_run:
            self.stdout.write("\nDry run completed. Use without --dry-run to apply changes.")
        else:
            self.stdout.write(self.style.SUCCESS("\nUpdate completed!"))
