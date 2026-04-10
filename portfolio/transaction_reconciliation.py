"""
Transaction Reconciliation Service
Handles merging and reconciling transactions from different sources (CAS, Kite, Manual)
"""
import logging
from datetime import date, datetime
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from .models import Portfolio, PortfolioFund, PurchaseLot, CASTransaction
from funds.models import MutualFund

logger = logging.getLogger(__name__)


class TransactionReconciliationService:
    """Service for reconciling transactions from different sources"""
    
    def __init__(self, user):
        self.user = user
        self.portfolio = Portfolio.get_or_create_for_user(user)
    
    def reconcile_all_transactions(self):
        """Reconcile all transactions for the user's portfolio"""
        logger.info(f"Starting transaction reconciliation for user {self.user.username}")
        
        reconciled_count = 0
        error_count = 0
        
        # Get all portfolio funds
        portfolio_funds = self.portfolio.holdings.select_related('fund').prefetch_related('lots', 'cas_transactions')
        
        for pf in portfolio_funds:
            try:
                result = self.reconcile_fund_transactions(pf)
                reconciled_count += result['reconciled']
                error_count += result['errors']
            except Exception as e:
                logger.error(f"Error reconciling fund {pf.fund.scheme_name}: {e}")
                error_count += 1
        
        logger.info(f"Transaction reconciliation completed: {reconciled_count} reconciled, {error_count} errors")
        
        return {
            'reconciled': reconciled_count,
            'errors': error_count
        }
    
    def reconcile_fund_transactions(self, portfolio_fund):
        """Reconcile transactions for a specific fund"""
        fund = portfolio_fund.fund
        logger.info(f"Reconciling transactions for fund: {fund.scheme_name}")
        
        # Get existing purchase lots
        existing_lots = list(portfolio_fund.lots.all())
        cas_transactions = list(portfolio_fund.cas_transactions.filter(is_processed=False))
        
        reconciled = 0
        errors = 0
        
        for cas_tx in cas_transactions:
            try:
                if self._should_create_lot_from_cas(cas_tx, existing_lots):
                    self._create_purchase_lot_from_cas(cas_tx, portfolio_fund)
                    reconciled += 1
                else:
                    # Mark as processed if no action needed
                    cas_tx.is_processed = True
                    cas_tx.save(update_fields=['is_processed'])
                    
            except Exception as e:
                logger.error(f"Error reconciling CAS transaction {cas_tx.id}: {e}")
                errors += 1
        
        # Update portfolio fund totals
        self._update_portfolio_fund_totals(portfolio_fund)
        
        return {
            'reconciled': reconciled,
            'errors': errors
        }
    
    def _should_create_lot_from_cas(self, cas_tx, existing_lots):
        """Determine if a purchase lot should be created from CAS transaction"""
        transaction_type = cas_tx.transaction_type
        
        # Only create lots for purchase-type transactions
        if transaction_type not in ['PURCHASE', 'SWITCH_IN', 'DIVIDEND_REINVEST']:
            return False
        
        # Check duplicate handling settings
        if self.cas_settings.duplicate_handling == 'SKIP':
            # Check for similar existing lot
            for lot in existing_lots:
                if (lot.purchase_date == cas_tx.transaction_date and 
                    abs(lot.units - cas_tx.units) < Decimal('0.0001') and
                    abs(lot.avg_nav - cas_tx.nav) < Decimal('0.0001') and
                    lot.source == 'CAS'):
                    return False
        
        return True
    
    def _create_purchase_lot_from_cas(self, cas_tx, portfolio_fund):
        """Create a purchase lot from CAS transaction"""
        with transaction.atomic():
            lot = PurchaseLot.objects.create(
                portfolio_fund=portfolio_fund,
                units=cas_tx.units,
                avg_nav=cas_tx.nav,
                purchase_date=cas_tx.transaction_date,
                source='CAS',
                transaction_type=cas_tx.transaction_type,
                cas_transaction_id=str(cas_tx.id),
                folio_number=cas_tx.folio_number,
                original_amount=cas_tx.amount,
                notes=self.cas_settings.default_notes or f"Imported from CAS - {cas_tx.transaction_date}"
            )
            
            # Link to CAS transaction
            cas_tx.purchase_lot = lot
            cas_tx.is_processed = True
            cas_tx.save(update_fields=['purchase_lot', 'is_processed'])
            
            logger.info(f"Created purchase lot from CAS transaction: {lot}")
    
    def _update_portfolio_fund_totals(self, portfolio_fund):
        """Update portfolio fund calculated totals"""
        # This will trigger the property calculations
        portfolio_fund.save(update_fields=[])
    
    def merge_duplicate_lots(self, portfolio_fund=None):
        """Merge duplicate purchase lots within a fund or all funds"""
        logger.info(f"Starting duplicate lot merge for user {self.user.username}")
        
        if portfolio_fund:
            funds = [portfolio_fund]
        else:
            funds = self.portfolio.holdings.select_related('fund').prefetch_related('lots')
        
        merged_count = 0
        
        for pf in funds:
            merged_count += self._merge_fund_duplicates(pf)
        
        logger.info(f"Duplicate lot merge completed: {merged_count} lots merged")
        return merged_count
    
    def _merge_fund_duplicates(self, portfolio_fund):
        """Merge duplicate lots within a specific fund"""
        lots = list(portfolio_fund.lots.order_by('purchase_date', 'avg_nav'))
        merged_count = 0
        
        i = 0
        while i < len(lots):
            current_lot = lots[i]
            
            # Look for potential duplicates
            duplicates = [current_lot]
            j = i + 1
            
            while j < len(lots):
                candidate = lots[j]
                if self._are_lots_duplicate(current_lot, candidate):
                    duplicates.append(candidate)
                    lots.pop(j)  # Remove from list
                else:
                    j += 1
            
            # If we found duplicates, merge them
            if len(duplicates) > 1:
                self._merge_lot_group(duplicates)
                merged_count += len(duplicates) - 1
                i += 1  # Skip the merged lots
            else:
                i += 1
        
        return merged_count
    
    def _are_lots_duplicate(self, lot1, lot2):
        """Check if two lots are likely duplicates"""
        # Same date and same NAV
        if lot1.purchase_date != lot2.purchase_date:
            return False
        
        if abs(lot1.avg_nav - lot2.avg_nav) > Decimal('0.01'):
            return False
        
        # Same source type
        if lot1.source != lot2.source:
            return False
        
        # Similar units (allowing for small rounding differences)
        if abs(lot1.units - lot2.units) > Decimal('0.001'):
            return False
        
        return True
    
    def _merge_lot_group(self, lots):
        """Merge a group of duplicate lots"""
        if len(lots) < 2:
            return
        
        # Keep the first lot as the primary
        primary_lot = lots[0]
        duplicate_lots = lots[1:]
        
        with transaction.atomic():
            # Calculate merged values
            total_units = sum(lot.units for lot in lots)
            total_amount = sum(lot.units * lot.avg_nav for lot in lots)
            merged_avg_nav = total_amount / total_units if total_units > 0 else Decimal('0')
            
            # Update primary lot
            primary_lot.units = total_units
            primary_lot.avg_nav = merged_avg_nav
            primary_lot.notes = f"Merged from {len(lots)} lots - {primary_lot.notes}"
            primary_lot.save(update_fields=['units', 'avg_nav', 'notes'])
            
            # Update CAS transactions to point to primary lot
            for lot in duplicate_lots:
                CASTransaction.objects.filter(purchase_lot=lot).update(purchase_lot=primary_lot)
                
                # Delete duplicate lot
                lot.delete()
            
            logger.info(f"Merged {len(lots)} lots for {primary_lot.portfolio_fund.fund.scheme_name}")
    
    def calculate_source_priority(self, data_sources):
        """Determine which data source has priority based on user settings"""
        priority = self.cas_settings.data_source_priority
        
        if priority == 'CAS_FIRST':
            return ['CAS', 'KITE', 'MANUAL']
        elif priority == 'KITE_FIRST':
            return ['KITE', 'CAS', 'MANUAL']
        elif priority == 'MOST_RECENT':
            # Sort by creation date, most recent first
            return sorted(data_sources, key=lambda x: x['created_at'], reverse=True)
        else:
            return ['CAS', 'KITE', 'MANUAL']
    
    def get_transaction_summary(self):
        """Get a summary of transactions by source and type"""
        summary = {
            'total_lots': 0,
            'by_source': {},
            'by_type': {},
            'by_fund': {}
        }
        
        lots = PurchaseLot.objects.filter(portfolio_fund__portfolio=self.portfolio)
        summary['total_lots'] = lots.count()
        
        # Group by source
        for lot in lots:
            source = lot.source
            if source not in summary['by_source']:
                summary['by_source'][source] = {'count': 0, 'total_amount': Decimal('0')}
            summary['by_source'][source]['count'] += 1
            summary['by_source'][source]['total_amount'] += lot.invested_amount
        
        # Group by transaction type
        for lot in lots:
            tx_type = lot.transaction_type
            if tx_type not in summary['by_type']:
                summary['by_type'][tx_type] = {'count': 0, 'total_amount': Decimal('0')}
            summary['by_type'][tx_type]['count'] += 1
            summary['by_type'][tx_type]['total_amount'] += lot.invested_amount
        
        # Group by fund
        for lot in lots:
            fund_name = lot.portfolio_fund.fund.scheme_name
            if fund_name not in summary['by_fund']:
                summary['by_fund'][fund_name] = {'count': 0, 'total_amount': Decimal('0')}
            summary['by_fund'][fund_name]['count'] += 1
            summary['by_fund'][fund_name]['total_amount'] += lot.invested_amount
        
        return summary


# Singleton service function
def get_transaction_reconciliation_service(user):
    """Get transaction reconciliation service for a user"""
    return TransactionReconciliationService(user)
