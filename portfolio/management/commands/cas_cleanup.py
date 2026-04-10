from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from portfolio.models import CASImport, CASTransaction, PurchaseLot
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up old CAS data and orphaned records'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete imports older than this many days (default: 90)'
        )
        parser.add_argument(
            '--failed-only',
            action='store_true',
            help='Only clean up failed imports'
        )
        parser.add_argument(
            '--orphaned-only',
            action='store_true',
            help='Only clean up orphaned transactions (no linked import)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt'
        )
    
    def handle(self, *args, **options):
        days = options.get('days', 90)
        failed_only = options.get('failed_only', False)
        orphaned_only = options.get('orphaned_only', False)
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No deletions will be performed'))
        
        self.stdout.write(f'Cleanup Configuration:')
        self.stdout.write(f'  Delete imports older than: {cutoff_date.strftime("%Y-%m-%d %H:%M")} ({days} days)')
        self.stdout.write(f'  Failed imports only: {failed_only}')
        self.stdout.write(f'  Orphaned transactions only: {orphaned_only}')
        self.stdout.write(f'  Dry run: {dry_run}')
        self.stdout.write('')
        
        total_imports_deleted = 0
        total_transactions_deleted = 0
        total_lots_orphaned = 0
        
        if not orphaned_only:
            # Clean up old CAS imports
            imports_query = CASImport.objects.filter(created_at__lt=cutoff_date)
            
            if failed_only:
                imports_query = imports_query.filter(status='FAILED')
            
            imports_to_delete = list(imports_query.select_related('user').prefetch_related('transactions'))
            
            if imports_to_delete:
                self.stdout.write(f'Found {len(imports_to_delete)} CAS imports to delete:')
                
                for imp in imports_to_delete:
                    transaction_count = imp.transactions.count()
                    self.stdout.write(f'  - {imp.filename} ({imp.user.username}, {imp.status}, {transaction_count} transactions)')
                
                if not dry_run and (force or self.confirm_deletion(len(imports_to_delete), 'imports')):
                    # Delete imports (this will cascade delete transactions)
                    for imp in imports_to_delete:
                        transaction_count = imp.transactions.count()
                        imp.delete()
                        total_imports_deleted += 1
                        total_transactions_deleted += transaction_count
                        
                        # Check for orphaned purchase lots
                        orphaned_lots = PurchaseLot.objects.filter(
                            source='CAS',
                            cas_transaction_id__isnull=False,
                            cas_transaction__isnull=True
                        ).count()
                        total_lots_orphaned += orphaned_lots
                else:
                    self.stdout.write('  Skipped import deletion')
            else:
                self.stdout.write('No CAS imports found matching criteria')
        
        # Clean up orphaned transactions
        orphaned_transactions = CASTransaction.objects.filter(cas_import__isnull=True)
        
        if orphaned_transactions.exists():
            self.stdout.write(f'\nFound {orphaned_transactions.count()} orphaned transactions to delete:')
            
            if not dry_run and (force or self.confirm_deletion(orphaned_transactions.count(), 'orphaned transactions')):
                orphaned_transactions.delete()
                total_transactions_deleted += orphaned_transactions.count()
                self.stdout.write('  Deleted orphaned transactions')
            else:
                self.stdout.write('  Skipped orphaned transaction deletion')
        else:
            self.stdout.write('\nNo orphaned transactions found')
        
        # Clean up orphaned purchase lots (lots with CAS source but no valid transaction reference)
        orphaned_lots = PurchaseLot.objects.filter(
            source='CAS'
        ).filter(
            Q(cas_transaction_id__isnull=True) | Q(cas_transaction__isnull=True)
        )
        
        if orphaned_lots.exists():
            self.stdout.write(f'\nFound {orphaned_lots.count()} orphaned purchase lots to delete:')
            
            # Show some details
            for lot in orphaned_lots[:5]:  # Show first 5
                self.stdout.write(f'  - {lot.portfolio_fund.fund.scheme_name} ({lot.units} @ {lot.avg_nav})')
            if orphaned_lots.count() > 5:
                self.stdout.write(f'  ... and {orphaned_lots.count() - 5} more')
            
            if not dry_run and (force or self.confirm_deletion(orphaned_lots.count(), 'orphaned purchase lots')):
                orphaned_lots.delete()
                total_lots_orphaned += orphaned_lots.count()
                self.stdout.write('  Deleted orphaned purchase lots')
            else:
                self.stdout.write('  Skipped orphaned purchase lot deletion')
        else:
            self.stdout.write('\nNo orphaned purchase lots found')
        
        # Summary
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('CLEANUP SUMMARY')
        self.stdout.write('=' * 50)
        self.stdout.write(f'Imports deleted: {total_imports_deleted}')
        self.stdout.write(f'Transactions deleted: {total_transactions_deleted}')
        self.stdout.write(f'Purchase lots orphaned/deleted: {total_lots_orphaned}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN COMPLETED - No files were deleted'))
        else:
            if total_imports_deleted > 0 or total_transactions_deleted > 0 or total_lots_orphaned > 0:
                self.stdout.write(self.style.SUCCESS('\nCLEANUP COMPLETED'))
            else:
                self.stdout.write(self.style.SUCCESS('\nNO CLEANUP NEEDED'))
    
    def confirm_deletion(self, count, item_type):
        """Ask for user confirmation before deletion"""
        self.stdout.write(self.style.WARNING(f'\nAbout to delete {count} {item_type}.'))
        response = input('Are you sure you want to continue? [y/N]: ')
        return response.lower().startswith('y')
