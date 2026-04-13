from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from portfolio.transaction_reconciliation import get_transaction_reconciliation_service
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reconcile CAS transactions with existing portfolio data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Username to reconcile (if not provided, reconciles all users)'
        )
        parser.add_argument(
            '--merge-duplicates',
            action='store_true',
            help='Merge duplicate purchase lots after reconciliation'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
    
    def handle(self, *args, **options):
        username = options.get('user')
        merge_duplicates = options.get('merge_duplicates', False)
        dry_run = options.get('dry_run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        if username:
            try:
                user = User.objects.get(username=username)
                users = [user]
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                return
        else:
            users = User.objects.all()
        
        total_reconciled = 0
        total_errors = 0
        total_merged = 0
        
        for user in users:
            self.stdout.write(f'Processing user: {user.username}')
            
            try:
                service = get_transaction_reconciliation_service(user)
                
                if not dry_run:
                    result = service.reconcile_all_transactions()
                    reconciled = result['reconciled']
                    errors = result['errors']
                    
                    if merge_duplicates:
                        merged = service.merge_duplicate_lots()
                        total_merged += merged
                else:
                    # In dry run mode, just show what would be processed
                    summary = service.get_transaction_summary()
                    reconciled = summary['total_lots']
                    errors = 0
                    self.stdout.write(f'  Would process {reconciled} lots')
                
                total_reconciled += reconciled
                total_errors += errors
                
                if reconciled > 0:
                    self.stdout.write(f'  ✓ Reconciled {reconciled} transactions')
                if errors > 0:
                    self.stdout.write(f'  ✗ {errors} errors')
                if merge_duplicates and not dry_run:
                    self.stdout.write(f'  ✓ Merged {merged} duplicate lots')
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Error processing user {user.username}: {e}'))
                total_errors += 1
        
        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write('RECONCILIATION SUMMARY')
        self.stdout.write('='*50)
        self.stdout.write(f'Users processed: {len(users)}')
        self.stdout.write(f'Transactions reconciled: {total_reconciled}')
        self.stdout.write(f'Errors: {total_errors}')
        if merge_duplicates:
            self.stdout.write(f'Duplicate lots merged: {total_merged}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN COMPLETED - No changes were made'))
        else:
            if total_errors == 0:
                self.stdout.write(self.style.SUCCESS('\nRECONCILIATION COMPLETED SUCCESSFULLY'))
            else:
                self.stdout.write(self.style.WARNING(f'\nRECONCILIATION COMPLETED WITH {total_errors} ERRORS'))
