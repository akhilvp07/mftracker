from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Q
from portfolio.models import CASImport, CASTransaction, PurchaseLot
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Show CAS import statistics and analytics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Show stats for specific user only'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to look back for recent activity (default: 30)'
        )
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed transaction breakdown'
        )
    
    def handle(self, *args, **options):
        username = options.get('user')
        days = options.get('days', 30)
        detailed = options.get('detailed', False)
        
        # Date range for recent activity
        since_date = datetime.now() - timedelta(days=days)
        
        self.stdout.write(self.style.SUCCESS('CAS IMPORT STATISTICS'))
        self.stdout.write('=' * 50)
        
        # Filter users if specified
        if username:
            try:
                user = User.objects.get(username=username)
                users = [user]
                self.stdout.write(f'Showing stats for user: {username}')
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                return
        else:
            users = User.objects.all()
            self.stdout.write(f'Showing stats for all users')
        
        self.stdout.write(f'Period: Last {days} days')
        self.stdout.write('')
        
        # Overall Statistics
        total_imports = CASImport.objects.filter(user__in=users)
        recent_imports = total_imports.filter(created_at__gte=since_date)
        
        self.stdout.write('OVERALL STATISTICS')
        self.stdout.write('-' * 20)
        self.stdout.write(f'Total CAS Imports: {total_imports.count()}')
        self.stdout.write(f'Recent Imports (last {days} days): {recent_imports.count()}')
        
        # Status breakdown
        status_breakdown = total_imports.values('status').annotate(count=Count('id'))
        for status in status_breakdown:
            status_display = status['status'].replace('_', ' ').title()
            self.stdout.write(f'  {status_display}: {status["count"]}')
        
        # Processing results
        completed_imports = total_imports.filter(status='COMPLETED')
        if completed_imports.exists():
            total_funds = completed_imports.aggregate(total=Sum('funds_processed'))['total'] or 0
            total_transactions = completed_imports.aggregate(total=Sum('transactions_processed'))['total'] or 0
            total_errors = completed_imports.aggregate(total=Sum('errors_count'))['total'] or 0
            
            self.stdout.write(f'Funds Processed: {total_funds}')
            self.stdout.write(f'Transactions Processed: {total_transactions}')
            self.stdout.write(f'Total Errors: {total_errors}')
        
        self.stdout.write('')
        
        # Transaction Statistics
        cas_transactions = CASTransaction.objects.filter(cas_import__user__in=users)
        recent_transactions = cas_transactions.filter(transaction_date__gte=since_date)
        
        self.stdout.write('TRANSACTION STATISTICS')
        self.stdout.write('-' * 25)
        self.stdout.write(f'Total CAS Transactions: {cas_transactions.count()}')
        self.stdout.write(f'Recent Transactions: {recent_transactions.count()}')
        
        # Transaction type breakdown
        if detailed:
            type_breakdown = cas_transactions.values('transaction_type').annotate(
                count=Count('id'),
                total_amount=Sum('amount'),
                total_units=Sum('units')
            ).order_by('-count')
            
            self.stdout.write('\nTransaction Type Breakdown:')
            for tx_type in type_breakdown:
                type_display = tx_type['transaction_type'].replace('_', ' ').title()
                amount = tx_type['total_amount'] or 0
                units = tx_type['total_units'] or 0
                self.stdout.write(f'  {type_display}:')
                self.stdout.write(f'    Count: {tx_type["count"]}')
                self.stdout.write(f'    Total Amount: ₹{amount:,.2f}')
                self.stdout.write(f'    Total Units: {units:,.4f}')
        
        # Purchase Lot Statistics
        cas_lots = PurchaseLot.objects.filter(source='CAS', portfolio_fund__portfolio__user__in=users)
        
        self.stdout.write('\nPURCHASE LOT STATISTICS')
        self.stdout.write('-' * 25)
        self.stdout.write(f'Total CAS Purchase Lots: {cas_lots.count()}')
        
        if cas_lots.exists():
            total_invested = cas_lots.aggregate(total=Sum('units') * Sum('avg_nav'))['total'] or 0
            # Calculate total invested correctly
            total_invested = sum(lot.invested_amount for lot in cas_lots)
            
            self.stdout.write(f'Total Invested via CAS: ₹{total_invested:,.2f}')
            
            # Source comparison
            all_lots = PurchaseLot.objects.filter(portfolio_fund__portfolio__user__in=users)
            source_breakdown = all_lots.values('source').annotate(count=Count('id')).order_by('-count')
            
            self.stdout.write('\nData Source Breakdown:')
            for source in source_breakdown:
                source_display = source['source'].replace('_', ' ').title()
                percentage = (source['count'] / all_lots.count()) * 100
                self.stdout.write(f'  {source_display}: {source["count"]} ({percentage:.1f}%)')
        
        # User-specific details if only one user
        if len(users) == 1:
            user = users[0]
            self.stdout.write(f'\nUSER DETAILS: {user.username}')
            self.stdout.write('-' * (15 + len(user.username)))
            
            user_imports = total_imports.filter(user=user)
            user_transactions = cas_transactions.filter(cas_import__user=user)
            user_lots = cas_lots.filter(portfolio_fund__portfolio__user=user)
            
            self.stdout.write(f'Imports: {user_imports.count()}')
            self.stdout.write(f'Transactions: {user_transactions.count()}')
            self.stdout.write(f'Purchase Lots: {user_lots.count()}')
            
            if user_lots.exists():
                user_invested = sum(lot.invested_amount for lot in user_lots)
                self.stdout.write(f'Total Invested: ₹{user_invested:,.2f}')
            
            # Recent activity
            recent_user_imports = user_imports.filter(created_at__gte=since_date)
            if recent_user_imports.exists():
                self.stdout.write(f'Recent Imports: {recent_user_imports.count()}')
                last_import = recent_user_imports.order_by('-created_at').first()
                self.stdout.write(f'Last Import: {last_import.created_at.strftime("%Y-%m-%d %H:%M")}')
        
        # Error Analysis
        failed_imports = total_imports.filter(status='FAILED')
        if failed_imports.exists():
            self.stdout.write(f'\nERROR ANALYSIS')
            self.stdout.write('-' * 15)
            self.stdout.write(f'Failed Imports: {failed_imports.count()}')
            
            # Common error patterns
            error_messages = failed_imports.values('error_message').annotate(
                count=Count('id')
            ).order_by('-count')[:5]
            
            if error_messages:
                self.stdout.write('Common Errors:')
                for error in error_messages:
                    if error['error_message']:
                        # Truncate long error messages
                        msg = error['error_message'][:60] + '...' if len(error['error_message']) > 60 else error['error_message']
                        self.stdout.write(f'  "{msg}" ({error["count"]} times)')
        
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS('STATISTICS COMPLETE'))
