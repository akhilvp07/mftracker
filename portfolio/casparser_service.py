"""
CAS Parser Integration Service
Handles parsing CAS PDFs and extracting transaction data using local casparser module
"""
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Union
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
import casparser
from casparser.exceptions import CASParseError, IncorrectPasswordError

from .models import CASImport, CASTransaction, PortfolioFund, PurchaseLot, Portfolio
from funds.models import MutualFund

logger = logging.getLogger(__name__)


class CASParserService:
    """Service for parsing CAS PDFs using local casparser module"""
    
    def __init__(self):
        self.use_local_parser = True  # Use local casparser module
        
    def parse_cas_pdf(self, pdf_file: InMemoryUploadedFile, password: str, user, incremental=True) -> CASImport:
        """
        Parse CAS PDF using local casparser module
        
        Args:
            pdf_file: Uploaded CAS PDF file
            password: PAN number (usually the PDF password)
            user: User object for tracking
            incremental: If True, only process new transactions (default)
            
        Returns:
            CASImport object with parsing results
        """
        # Generate file hash for duplicate detection
        import hashlib
        file_hash = hashlib.md5()
        pdf_file.seek(0)
        for chunk in iter(lambda: pdf_file.read(4096), b""):
            file_hash.update(chunk)
        pdf_file.seek(0)
        file_hash = file_hash.hexdigest()
        
        # Create import record
        cas_import = CASImport.objects.create(
            user=user,
            filename=pdf_file.name,
            file_size=pdf_file.size,
            file_hash=file_hash,
            status='PENDING'
        )
        
        if incremental:
            try:
                logger.info(f"Starting CAS parse for user: {user}, file: {pdf_file.name}")
                
                # Parse using local casparser
                logger.info(f"Parsing CAS PDF using local casparser: {pdf_file.name}")
                
                # Parse the PDF - pass the file-like object directly
                cas_data = casparser.read_cas_pdf(
                    filename=pdf_file,
                    password=password,
                    output='dict'
                )
                
                # Convert CASData object to dictionary
                result = cas_data.dict()
                
                # Convert Decimal and date objects to strings for JSON serialization
                import json
                def convert_decimals(obj):
                    if isinstance(obj, Decimal):
                        return str(obj)
                    elif isinstance(obj, (date, datetime)):
                        return obj.isoformat()
                    elif isinstance(obj, dict):
                        return {k: convert_decimals(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_decimals(item) for item in obj]
                    return obj
                
                result = convert_decimals(result)
                
                logger.info(f"CAS parsing completed. Found {len(result.get('folios', []))} folios")
                
                # Store parser response
                cas_import.parser_response = result
                
                # Extract basic information
                self._extract_basic_info(cas_import, result)
                
                # Validate that this CAS is not older than existing data
                if incremental:
                    validation_result = self._validate_cas_recency(user, cas_import)
                    if not validation_result['valid']:
                        error_msg = validation_result['error']
                        logger.warning(f"Rejected CAS upload: {error_msg}")
                        cas_import.mark_completed(success=False, error_message=error_msg)
                        return cas_import
                    
                    # Check if we need special handling for overlapping periods
                    strategy = self._determine_sync_strategy(user, cas_import)
                    
                    if strategy == 'INCREMENTAL':
                        self._cache_existing_transactions(user)
                        self._process_mutual_funds_incremental(cas_import, result, user)
                    elif strategy == 'REPLACE_PERIOD':
                        self._replace_period_data(cas_import, result, user)
                    else:  # FULL_SYNC
                        self._full_sync(cas_import, result, user)
                else:
                    self._process_mutual_funds(cas_import, result, user)
                
                # Mark as completed
                cas_import.mark_completed(success=True)
                
                logger.info(f"Successfully processed CAS import {cas_import.id} for user {user.username}")
                
            except IncorrectPasswordError:
                error_msg = "Incorrect password. Please check the password you entered."
                logger.error(f"CAS parsing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
                
            except CASParseError as e:
                error_msg = f"Failed to parse CAS PDF: {str(e)}"
                logger.error(f"CAS parsing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
                
            except Exception as e:
                error_msg = f"Processing failed: {str(e)}"
                logger.error(f"CAS processing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
            
            return cas_import
        else:
            # Non-incremental processing
            try:
                logger.info(f"Starting CAS parse for user: {user}, file: {pdf_file.name}")
                
                # Parse using local casparser
                logger.info(f"Parsing CAS PDF using local casparser: {pdf_file.name}")
                
                # Parse the PDF - pass the file-like object directly
                cas_data = casparser.read_cas_pdf(
                    filename=pdf_file,
                    password=password,
                    output='dict'
                )
                
                # Convert CASData object to dictionary
                result = cas_data.dict()
                
                # Convert Decimal and date objects to strings for JSON serialization
                import json
                def convert_decimals(obj):
                    if isinstance(obj, Decimal):
                        return str(obj)
                    elif isinstance(obj, (date, datetime)):
                        return obj.isoformat()
                    elif isinstance(obj, dict):
                        return {k: convert_decimals(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_decimals(item) for item in obj]
                    return obj
                
                result = convert_decimals(result)
                
                logger.info(f"CAS parsing completed. Found {len(result.get('folios', []))} folios")
                
                # Store parser response
                cas_import.parser_response = result
                
                # Extract basic information
                self._extract_basic_info(cas_import, result)
                
                # Process all mutual funds
                self._process_mutual_funds(cas_import, result, user)
                
                # Mark as completed
                cas_import.mark_completed(success=True)
                
                logger.info(f"Successfully processed CAS import {cas_import.id} for user {user.username}")
                
            except IncorrectPasswordError:
                error_msg = "Incorrect password. Please check the password you entered."
                logger.error(f"CAS parsing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
                
            except CASParseError as e:
                error_msg = f"Failed to parse CAS PDF: {str(e)}"
                logger.error(f"CAS parsing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
                
            except Exception as e:
                error_msg = f"Processing failed: {str(e)}"
                logger.error(f"CAS processing error: {error_msg}")
                cas_import.mark_completed(success=False, error_message=error_msg)
            
            return cas_import
    
    def _extract_basic_info(self, cas_import: CASImport, result: Dict):
        """Extract basic information from CAS response"""
        # Extract investor info
        investor_info = result.get('investor_info', {})
        if investor_info:
            cas_import.investor_name = investor_info.get('name')
            cas_import.investor_pan = investor_info.get('PAN')
        
        # Extract statement period
        statement_period = result.get('statement_period', {})
        if statement_period:
            # Convert from "10-Apr-2026" format to date
            from datetime import datetime
            date_format = '%d-%b-%Y'  # Format like "10-Apr-2026"
            
            if statement_period.get('from'):
                cas_import.statement_period_from = datetime.strptime(statement_period.get('from'), date_format).date()
            if statement_period.get('to'):
                cas_import.statement_period_to = datetime.strptime(statement_period.get('to'), date_format).date()
        
        # Extract CAS type
        cas_import.cas_type = result.get('cas_type', 'UNKNOWN')
        
        # Extract file type
        cas_import.file_type = result.get('file_type', 'UNKNOWN')
        
        # Save basic info
        cas_import.save(update_fields=[
            'investor_name', 'investor_pan', 'cas_type',
            'statement_period_from', 'statement_period_to',
            'parser_response'
        ])
    
    def _process_mutual_funds(self, cas_import: CASImport, result: Dict, user):
        """Process mutual funds data from CAS response"""
        total_funds = 0
        total_transactions = 0
        
        # Process folios from casparser data
        folios = result.get('folios', [])
        logger.info(f"Processing {len(folios)} folios from CAS")
        
        if not folios:
            logger.warning(f"No folios found in CAS import {cas_import.id}")
            return
        
        for folio_data in folios:
            folio_number = folio_data.get('folio', '')
            schemes = folio_data.get('schemes', [])
            
            for scheme_data in schemes:
                try:
                    # Get or create mutual fund from scheme data
                    fund = self._get_or_create_fund_from_scheme(scheme_data)
                    if not fund:
                        continue
                    
                    # Get or create portfolio fund
                    portfolio_fund = self._get_or_create_portfolio_fund(user, fund)
                    if not portfolio_fund:
                        continue
                    
                    # Process transactions
                    transactions = scheme_data.get('transactions', [])
                    for tx_data in transactions:
                        self._process_transaction(
                            cas_import, portfolio_fund, fund, tx_data, folio_data
                        )
                        total_transactions += 1
                    
                    # Update holdings if there are no valid transactions
                    valid_transactions = [t for t in transactions if self._safe_decimal(t.get('units')) != 0]
                    if not valid_transactions:
                        self._update_current_holdings(portfolio_fund, scheme_data, folio_data)
                    
                    total_funds += 1
                
                except Exception as e:
                    logger.error(f"Error processing scheme in CAS import: {e}")
                    cas_import.errors_count += 1
        
        # Update counts
        cas_import.funds_processed = total_funds
        cas_import.transactions_processed = total_transactions
        cas_import.save(update_fields=['funds_processed', 'transactions_processed', 'errors_count'])
    
    def _get_or_create_fund_from_scheme(self, scheme_data: Dict) -> Optional[MutualFund]:
        """Find or create MutualFund from casparser scheme data with enhanced matching"""
        # Extract data
        isin = scheme_data.get('isin')
        amfi_code = scheme_data.get('amfi')
        scheme_name = scheme_data.get('scheme')
        fund_house = scheme_data.get('amc', 'Unknown')
        
        fund = None
        
        # Priority 1: Try AMFI code (most reliable for mergers)
        if amfi_code:
            try:
                fund = MutualFund.objects.get(scheme_code=amfi_code)
                # Check if ISIN changed (scheme merger)
                if isin and fund.isin and isin != fund.isin:
                    logger.warning(f"ISIN changed for scheme {amfi_code}: {fund.isin} -> {isin}")
                    fund.isin = isin
                    fund.save(update_fields=['isin'])
                logger.info(f"Found fund by AMFI code: {amfi_code}")
                return fund
            except MutualFund.DoesNotExist:
                pass
        
        # Priority 2: Try ISIN
        if isin:
            try:
                fund = MutualFund.objects.get(isin=isin)
                logger.info(f"Found fund by ISIN: {isin}")
                return fund
            except MutualFund.DoesNotExist:
                pass
        
        # Priority 3: Try scheme name with better matching
        if scheme_name:
            # Remove direct plan text for better matching
            clean_name = scheme_name.replace('- Direct Plan', '').replace('(Direct)', '').strip()
            try:
                fund = MutualFund.objects.get(scheme_name__iexact=clean_name)
                logger.info(f"Found fund by name: {scheme_name}")
                return fund
            except MutualFund.DoesNotExist:
                pass
            except MutualFund.MultipleObjectsReturned:
                # Try with fund house
                if fund_house and fund_house != 'Unknown':
                    try:
                        fund = MutualFund.objects.get(
                            scheme_name__iexact=clean_name,
                            amc__icontains=fund_house
                        )
                        logger.info(f"Found fund by name + AMC: {scheme_name}")
                        return fund
                    except MutualFund.DoesNotExist:
                        pass
        
        # Create new fund if we have enough data
        if scheme_name and (isin or amfi_code):
            try:
                fund = MutualFund.objects.create(
                    scheme_name=scheme_name,
                    isin=isin,
                    scheme_code=amfi_code,
                    fund_house=fund_house,
                    scheme_type=scheme_data.get('type', 'Unknown'),
                    current_nav=Decimal('0'),  # Will be updated later
                    nav_date=date.today()
                )
                logger.info(f"Created new fund from CAS: {scheme_name}")
                return fund
            except Exception as e:
                logger.error(f"Error creating fund from CAS: {e}")
        
        logger.warning(f"Could not find or create fund: {scheme_data}")
        return None
    
    def _get_or_create_portfolio_fund(self, user, fund: MutualFund) -> Optional[PortfolioFund]:
        """Get or create PortfolioFund for user and fund"""
        try:
            portfolio, _ = Portfolio.objects.get_or_create(user=user)
            portfolio_fund, created = PortfolioFund.objects.get_or_create(
                portfolio=portfolio,
                fund=fund
            )
            return portfolio_fund
        except Exception as e:
            logger.error(f"Error getting/creating portfolio fund: {e}")
            return None
    
    def _get_or_create_fund(self, fund_data: Dict) -> Optional[MutualFund]:
        """Find or create MutualFund from CAS data"""
        # Try to find by ISIN first
        isin = fund_data.get('isin')
        if isin:
            try:
                return MutualFund.objects.get(isin=isin)
            except MutualFund.DoesNotExist:
                pass
        
        # Try to find by scheme name
        scheme_name = fund_data.get('scheme_name') or fund_data.get('name')
        if scheme_name:
            try:
                return MutualFund.objects.get(scheme_name__iexact=scheme_name)
            except MutualFund.DoesNotExist:
                pass
        
        # Try to find by scheme code
        scheme_code = fund_data.get('scheme_code')
        if scheme_code:
            try:
                return MutualFund.objects.get(scheme_code=scheme_code)
            except MutualFund.DoesNotExist:
                pass
        
        # Create new fund if we have enough data
        if scheme_name and (isin or scheme_code):
            try:
                fund = MutualFund.objects.create(
                    scheme_name=scheme_name,
                    isin=isin,
                    scheme_code=scheme_code,
                    fund_house=fund_data.get('fund_house', 'Unknown'),
                    scheme_type=fund_data.get('scheme_type', 'Unknown'),
                    current_nav=Decimal('0'),  # Will be updated later
                    nav_date=date.today()
                )
                logger.info(f"Created new fund from CAS: {scheme_name}")
                return fund
            except Exception as e:
                logger.error(f"Error creating fund from CAS: {e}")
        
        logger.warning(f"Could not find or create fund: {fund_data}")
        return None
    
    def _safe_decimal(self, value):
        """Safely convert value to Decimal, handling None and empty strings"""
        if value is None or value == '' or value == 'None':
            return Decimal('0')
        try:
            return Decimal(str(value))
        except (ValueError, TypeError, decimal.InvalidOperation):
            return Decimal('0')
    
    def _process_transaction(self, cas_import: CASImport, portfolio_fund: PortfolioFund, 
                           fund: MutualFund, tx_data: Dict, folio_data: Dict = None):
        """Process individual transaction from CAS data"""
        try:
            import decimal
            # Map transaction types
            tx_type = self._map_transaction_type(tx_data.get('type', 'purchase'))
            
            # Parse transaction data
            tx_date = datetime.strptime(tx_data.get('date'), '%Y-%m-%d').date()
            units = self._safe_decimal(tx_data.get('units'))
            nav = self._safe_decimal(tx_data.get('nav'))
            amount = self._safe_decimal(tx_data.get('amount'))
            
            # Skip transactions with 0 units (invalid data) - don't create any records
            if units == 0:
                logger.warning(f"Skipping transaction with 0 units for {fund.scheme_name} on {tx_date}")
                cas_import.skipped_transactions += 1
                cas_import.save(update_fields=['skipped_transactions'])
                return
            
            # Create CAS transaction record
            cas_tx = CASTransaction.objects.create(
                cas_import=cas_import,
                portfolio_fund=portfolio_fund,
                fund=fund,
                transaction_type=tx_type,
                transaction_date=tx_date,
                units=units,
                nav=nav,
                amount=amount,
                folio_number=folio_data.get('folio', ''),  # Get folio from parent folio_data
                balance_units=self._safe_decimal(tx_data.get('balance')) if tx_data.get('balance') else None,
                raw_data=tx_data
            )
            
            # Create purchase lot for purchase transactions
            if tx_type in ['PURCHASE', 'SWITCH_IN', 'DIVIDEND_REINVEST']:
                self._create_purchase_lot(cas_tx, portfolio_fund, tx_data)
            elif tx_type in ['REDEMPTION', 'SWITCH_OUT']:
                self._process_redemption(cas_tx, portfolio_fund, tx_data)
            
            cas_tx.is_processed = True
            cas_tx.save(update_fields=['is_processed'])
            
        except Exception as e:
            logger.error(f"Error processing transaction: {e}")
            cas_import.errors_count += 1
    
    def _should_reconcile_holdings(self, portfolio_fund: PortfolioFund, scheme_data: Dict) -> bool:
        """Check if holdings need reconciliation"""
        try:
            cas_units = self._safe_decimal(scheme_data.get('units'))
            current_units = portfolio_fund.total_units
            
            # Reconcile if there's a significant difference
            return abs(cas_units - current_units) > Decimal('0.01')
        except:
            return False
    
    def _update_current_holdings(self, portfolio_fund: PortfolioFund, scheme_data: Dict, 
                              folio_data: Dict):
        """Update current holdings based on CAS data"""
        try:
            # Get current balance from CAS - use close balance from scheme
            units = self._safe_decimal(scheme_data.get('close'))
            
            # Get valuation data if available
            valuation = scheme_data.get('valuation', {})
            if valuation:
                value = self._safe_decimal(valuation.get('value'))
                nav = self._safe_decimal(valuation.get('nav'))
            else:
                value = Decimal('0')
                nav = Decimal('0')
            
            folio_number = folio_data.get('folio', '')
            
            # Only create holdings if units > 0
            if units > 0:
                # Remove any existing HOLDING lots for this folio
                PurchaseLot.objects.filter(
                    portfolio_fund=portfolio_fund,
                    source='CAS',
                    transaction_type='HOLDING',
                    folio_number=folio_number
                ).delete()
                
                # Check if there are any CAS transactions for this fund
                existing_lots = portfolio_fund.lots.filter(
                    source='CAS',
                    transaction_type__in=['PURCHASE', 'REDEMPTION', 'SWITCH_IN', 'SWITCH_OUT']
                ).exists()
                
                if not existing_lots:
                    # Create a single holding lot when no transactions exist
                    PurchaseLot.objects.create(
                        portfolio_fund=portfolio_fund,
                        units=units,
                        avg_nav=nav if nav > 0 else Decimal('0'),
                        purchase_date=date.today(),
                        source='CAS',
                        transaction_type='HOLDING',
                        folio_number=folio_number,
                        notes=f'Current holdings from CAS (no transaction history)',
                        is_open=True
                    )
                    logger.info(f"Created holdings lot for {portfolio_fund.fund.scheme_name}: {units} units")
                else:
                    # If there are transactions but units don't match, we might need to reconcile
                    current_units = portfolio_fund.total_units
                    if abs(current_units - units) > Decimal('0.01'):
                        logger.warning(f"Holding mismatch for {portfolio_fund.fund.scheme_name}: CAS={units}, Calculated={current_units}")
            
        except Exception as e:
            logger.error(f"Error updating holdings: {e}")
    
    def _map_transaction_type(self, tx_type: str) -> str:
        """Map CAS transaction types to our enum"""
        type_mapping = {
            'PURCHASE': 'PURCHASE',
            'PURCHASE_SIP': 'PURCHASE',
            'REDEMPTION': 'REDEMPTION',
            'SWITCH_IN': 'SWITCH_IN',
            'SWITCH_IN_MERGER': 'SWITCH_IN',
            'SWITCH_OUT': 'SWITCH_OUT',
            'SWITCH_OUT_MERGER': 'SWITCH_OUT',
            'DIVIDEND_PAYOUT': 'DIVIDEND',
            'DIVIDEND_REINVESTMENT': 'DIVIDEND_REINVEST',
            'SEGREGATION': 'SEGREGATION',
            'STAMP_DUTY_TAX': 'TAX',
            'TDS_TAX': 'TAX',
            'STT_TAX': 'TAX',
            'MISC': 'MISC',
        }
        return type_mapping.get(tx_type.upper(), 'PURCHASE')
    
    def _process_redemption(self, cas_tx: CASTransaction, portfolio_fund: PortfolioFund, 
                         tx_data: Dict):
        """Process redemption transaction - create separate redemption lot without modifying purchase lots"""
        try:
            # Check if this redemption was already processed
            existing_redemption = portfolio_fund.lots.filter(
                purchase_date=cas_tx.transaction_date,
                units=cas_tx.units,  # Keep the original units (negative for redemption)
                transaction_type__in=['REDEMPTION', 'SWITCH_OUT'],
                source='CAS'
            ).first()
            
            if existing_redemption:
                logger.info(f"Redemption already processed for {portfolio_fund.fund.scheme_name} on {cas_tx.transaction_date}")
                cas_tx.purchase_lot = existing_redemption
                cas_tx.save(update_fields=['purchase_lot'])
                return
            
            # Create redemption transaction record - don't modify existing purchase lots
            redemption_lot = PurchaseLot.objects.create(
                portfolio_fund=portfolio_fund,
                units=cas_tx.units,  # Keep negative units for redemption
                avg_nav=cas_tx.nav,
                purchase_date=cas_tx.transaction_date,
                source='CAS',
                transaction_type=cas_tx.transaction_type,
                folio_number=cas_tx.folio_number,
                original_amount=cas_tx.amount,
                notes=f'Redemption transaction',
                is_open=False
            )
            
            # Link CAS transaction to redemption lot
            cas_tx.purchase_lot = redemption_lot
            cas_tx.save(update_fields=['purchase_lot'])
            
            logger.info(f"Processed redemption of {abs(cas_tx.units)} units for {portfolio_fund.fund.scheme_name}")
            
        except Exception as e:
            logger.error(f"Error processing redemption: {e}")
    
    def _create_purchase_lot(self, cas_tx: CASTransaction, portfolio_fund: PortfolioFund, 
                           tx_data: Dict):
        """Create purchase lot from CAS transaction - never merge for CAS imports"""
        try:
            # Always create a new lot for CAS transactions
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
                notes=f"Imported from CAS - {cas_tx.transaction_date}"
            )
            
            # Link to CAS transaction
            cas_tx.purchase_lot = lot
            cas_tx.save(update_fields=['purchase_lot'])
            
            logger.info(f"Created purchase lot from CAS transaction: {lot}")
            
        except Exception as e:
            logger.error(f"Error creating purchase lot from CAS: {e}")
    
    def _merge_duplicate_lots(self, existing_lot: PurchaseLot, cas_tx: CASTransaction):
        """Merge duplicate lots from CAS with existing lots"""
        try:
            # Update existing lot with CAS data if it has more information
            updated = False
            notes = []
            
            # Update folio number if existing doesn't have one
            if cas_tx.folio_number and not existing_lot.folio_number:
                existing_lot.folio_number = cas_tx.folio_number
                updated = True
                notes.append(f"Added CAS folio: {cas_tx.folio_number}")
            
            # Update NAV if CAS has more accurate data
            if cas_tx.nav and cas_tx.nav != existing_lot.avg_nav:
                # Calculate weighted average if both have NAVs
                if existing_lot.avg_nav > 0:
                    # Weighted average: (existing_units * existing_nav + cas_units * cas_nav) / total_units
                    total_amount = (existing_lot.units * existing_lot.avg_nav + 
                                  cas_tx.units * cas_tx.nav)
                    existing_lot.avg_nav = total_amount / (existing_lot.units + cas_tx.units)
                    notes.append(f"Updated NAV with CAS data (weighted average)")
                else:
                    existing_lot.avg_nav = cas_tx.nav
                    notes.append(f"Updated NAV from CAS: {cas_tx.nav}")
                updated = True
            
            # Update source to reflect both sources
            if existing_lot.source != 'CAS' and existing_lot.source not in notes:
                notes.append(f"Merged with CAS data")
            
            # Update notes
            if notes:
                existing_lot.notes = f"{existing_lot.notes}\n" + " | ".join(notes) if existing_lot.notes else " | ".join(notes)
            
            if updated:
                existing_lot.save(update_fields=['folio_number', 'avg_nav', 'notes'])
                logger.info(f"Merged CAS data into existing lot for {existing_lot.portfolio_fund.fund.scheme_name}")
            else:
                logger.info(f"No updates needed for existing lot (CAS data already present)")
            
            # Link CAS transaction to existing lot
            cas_tx.purchase_lot = existing_lot
            cas_tx.save(update_fields=['purchase_lot'])
            
        except Exception as e:
            logger.error(f"Error merging duplicate lots: {e}")
    
    def get_import_history(self, user) -> List[CASImport]:
        """Get CAS import history for a user"""
        return CASImport.objects.filter(user=user).order_by('-created_at')
    
    def get_import_stats(self, user) -> Dict:
        """Get CAS import statistics for a user"""
        imports = CASImport.objects.filter(user=user)
        
        return {
            'total_imports': imports.count(),
            'successful_imports': imports.filter(status='COMPLETED').count(),
            'failed_imports': imports.filter(status='FAILED').count(),
            'total_funds': imports.aggregate(models.Sum('funds_processed'))['funds_processed__sum'] or 0,
            'total_transactions': imports.aggregate(models.Sum('transactions_processed'))['transactions_processed__sum'] or 0,
            'last_import': imports.first().created_at if imports.exists() else None
        }
    
    def _cache_existing_transactions(self, user):
        """Cache existing transactions for quick duplicate detection"""
        self.existing_transactions_cache = {}
        
        # Get user's portfolio funds first
        from portfolio.models import Portfolio, PortfolioFund
        user_portfolio = Portfolio.objects.filter(user=user).first()
        if not user_portfolio:
            return
        
        user_fund_ids = PortfolioFund.objects.filter(
            portfolio=user_portfolio
        ).values_list('fund_id', flat=True)
        
        # Get transactions for user's funds
        transactions = CASTransaction.objects.filter(
            fund_id__in=user_fund_ids
        ).select_related('fund')
        
        for tx in transactions:
            fund_key = str(tx.fund.isin) if tx.fund.isin else str(tx.fund.id)
            if fund_key not in self.existing_transactions_cache:
                self.existing_transactions_cache[fund_key] = set()
            
            # Create unique key for transaction
            tx_key = f"{tx.transaction_date}_{tx.units}_{tx.nav}_{tx.transaction_type}"
            self.existing_transactions_cache[fund_key].add(tx_key)
    
    def _is_transaction_processed(self, fund_isin: str, tx_data: Dict) -> bool:
        """Check if transaction was already processed"""
        # Try ISIN first, then try to find by ISIN to get ID
        fund_key = str(fund_isin)
        if fund_key not in self.existing_transactions_cache:
            # Try to find fund by ISIN and use its ID as key
            try:
                fund = MutualFund.objects.get(isin=fund_isin)
                fund_key = str(fund.id)
            except MutualFund.DoesNotExist:
                return False
            
        if fund_key not in self.existing_transactions_cache:
            return False
        
        tx_date = tx_data.get('date')
        units = str(tx_data.get('units', '0'))
        nav = str(tx_data.get('nav', '0'))
        tx_type = self._map_transaction_type(tx_data.get('type', 'purchase'))
        
        tx_key = f"{tx_date}_{units}_{nav}_{tx_type}"
        return tx_key in self.existing_transactions_cache[fund_key]
    
    def _process_mutual_funds_incremental(self, cas_import: CASImport, result: Dict, user):
        """Process mutual funds with incremental approach - only new transactions"""
        total_new_transactions = 0
        total_funds = 0
        
        folios = result.get('folios', [])
        
        for folio_data in folios:
            schemes = folio_data.get('schemes', [])
            
            for scheme_data in schemes:
                # Get or create fund
                fund = self._get_or_create_fund_from_scheme(scheme_data)
                if not fund:
                    continue
                
                # Get or create portfolio fund
                portfolio_fund = self._get_or_create_portfolio_fund(user, fund)
                if not portfolio_fund:
                    continue
                
                total_funds += 1
                
                # Process only new transactions
                transactions = scheme_data.get('transactions', [])
                new_count = 0
                
                for tx_data in transactions:
                    # Skip if already processed
                    if fund.isin and self._is_transaction_processed(fund.isin, tx_data):
                        continue
                    
                    # Process new transaction
                    self._process_transaction(
                        cas_import, portfolio_fund, fund, tx_data, folio_data
                    )
                    new_count += 1
                    
                    # Add to cache to avoid duplicates within same import
                    fund_key = str(fund.isin) if fund.isin else str(fund.id)
                    if fund_key not in self.existing_transactions_cache:
                        self.existing_transactions_cache[fund_key] = set()
                    
                    tx_date = tx_data.get('date')
                    units = str(tx_data.get('units', '0'))
                    nav = str(tx_data.get('nav', '0'))
                    tx_type = self._map_transaction_type(tx_data.get('type', 'purchase'))
                    
                    tx_key = f"{tx_date}_{units}_{nav}_{tx_type}"
                    self.existing_transactions_cache[fund_key].add(tx_key)
                
                total_new_transactions += new_count
                # Update holdings if there are new transactions
                if new_count > 0:
                    self._update_current_holdings(portfolio_fund, scheme_data, folio_data)
                
                total_new_transactions += new_count
        
        # Update counts
        cas_import.funds_processed = total_funds
        cas_import.transactions_processed = total_new_transactions
        cas_import.save(update_fields=['funds_processed', 'transactions_processed'])
    
    
    def _validate_cas_recency(self, user, cas_import: CASImport) -> Dict:
        """
        Validate that the uploaded CAS is not older than existing data
        
        Returns:
            Dict with 'valid' boolean and 'error' message if invalid
        """
        if not cas_import.statement_period_to:
            # No period info - allow but log warning
            logger.warning(f"CAS has no statement period, allowing upload")
            return {'valid': True}
        
        # Get the latest transaction date for this user
        latest_transaction = CASTransaction.objects.filter(
            cas_import__user=user
        ).order_by('-transaction_date').first()
        
        if not latest_transaction:
            # No existing transactions - allow
            return {'valid': True}
        
        # Check if new CAS end date is older than latest transaction
        if cas_import.statement_period_to < latest_transaction.transaction_date:
            days_diff = (latest_transaction.transaction_date - cas_import.statement_period_to).days
            
            return {
                'valid': False,
                'error': f"This CAS statement is outdated. Your latest transaction is from {latest_transaction.transaction_date.strftime('%d-%b-%Y')}, "
                        f"but this CAS only covers until {cas_import.statement_period_to.strftime('%d-%b-%Y')} ({days_diff} days old). "
                        f"Please upload a more recent CAS statement."
            }
        
        # Check if CAS is significantly old (more than 3 months from today)
        from datetime import timedelta
        three_months_ago = date.today() - timedelta(days=90)
        
        if cas_import.statement_period_to < three_months_ago:
            months_diff = (date.today() - cas_import.statement_period_to).days // 30
            
            return {
                'valid': False,
                'error': f"This CAS statement is too old. It covers until {cas_import.statement_period_to.strftime('%d-%b-%Y')} "
                        f"({months_diff} months ago). Please upload a recent CAS statement (within last 3 months)."
            }
        
        return {'valid': True}
    
    def _determine_sync_strategy(self, user, cas_import: CASImport) -> str:
        """
        Determine the best sync strategy based on existing data and new CAS period
        
        Returns:
            'INCREMENTAL': Only add new transactions
            'REPLACE_PERIOD': Replace transactions for the specific period
            'FULL_SYNC': Full re-sync (delete and re-import)
        """
        if not cas_import.statement_period_from or not cas_import.statement_period_to:
            # No period info - use incremental
            return 'INCREMENTAL'
        
        # Get existing statement periods
        existing_imports = CASImport.objects.filter(
            user=user,
            status='COMPLETED'
        ).exclude(
            statement_period_from__isnull=True,
            statement_period_to__isnull=True
        ).order_by('statement_period_from')
        
        if not existing_imports:
            return 'INCREMENTAL'
        
        # Check for overlaps
        for existing in existing_imports:
            # If new CAS completely covers existing period
            if (cas_import.statement_period_from <= existing.statement_period_from and 
                cas_import.statement_period_to >= existing.statement_period_to):
                logger.info(f"New CAS covers existing period: replacing {existing.statement_period_from} to {existing.statement_period_to}")
                return 'REPLACE_PERIOD'
            
            # If new CAS is within existing period
            if (cas_import.statement_period_from >= existing.statement_period_from and 
                cas_import.statement_period_to <= existing.statement_period_to):
                # Assume it's additional data (e.g., more detailed transactions)
                return 'INCREMENTAL'
            
            # If periods overlap partially
            if not (cas_import.statement_period_to < existing.statement_period_from or 
                   cas_import.statement_period_from > existing.statement_period_to):
                # Partial overlap - use full sync for safety
                logger.warning(f"Partial overlap detected: new({cas_import.statement_period_from} to {cas_import.statement_period_to}) vs "
                             f"existing({existing.statement_period_from} to {existing.statement_period_to})")
                return 'FULL_SYNC'
        
        # No overlaps - incremental is safe
        return 'INCREMENTAL'
    
    def _replace_period_data(self, cas_import: CASImport, result: Dict, user):
        """
        Replace transactions for a specific period
        Used when new CAS completely covers an existing period
        """
        from django.db import transaction
        from datetime import datetime
        
        with transaction.atomic():
            # Find and delete transactions in the period
            deleted_count = 0
            folios = result.get('folios', [])
            
            # Get all funds in this CAS
            fund_isins = set()
            for folio in folios:
                for scheme in folio.get('schemes', []):
                    if scheme.get('isin'):
                        fund_isins.add(scheme['isin'])
            
            # Delete transactions for these funds within the period
            for isin in fund_isins:
                try:
                    fund = MutualFund.objects.get(isin=isin)
                    deleted = CASTransaction.objects.filter(
                        fund=fund,
                        transaction_date__gte=cas_import.statement_period_from,
                        transaction_date__lte=cas_import.statement_period_to,
                        cas_import__user=user
                    ).delete()
                    deleted_count += deleted[0] if deleted else 0
                except MutualFund.DoesNotExist:
                    continue
            
            logger.info(f"Deleted {deleted_count} transactions for period {cas_import.statement_period_from} to {cas_import.statement_period_to}")
            
            # Import all transactions from new CAS
            self._process_mutual_funds(cas_import, result, user)
            
            # Update holdings for affected funds
            self._update_holdings_for_period(user, result, cas_import.statement_period_from, cas_import.statement_period_to)
    
    def _full_sync(self, cas_import: CASImport, result: Dict, user):
        """
        Full synchronization - delete all CAS transactions and re-import
        Used when there are complex overlaps or inconsistencies
        """
        from django.db import transaction
        
        with transaction.atomic():
            # Delete all CAS transactions for the user
            deleted_count = CASTransaction.objects.filter(
                cas_import__user=user
            ).delete()
            
            logger.info(f"Full sync: Deleted {deleted_count[0]} CAS transactions")
            
            # Import all transactions
            self._process_mutual_funds(cas_import, result, user)
            
            # Update all holdings
            self._update_all_holdings_from_cas(user, result)
    
    def _update_holdings_for_period(self, user, result: Dict, period_from: date, period_to: date):
        """Update holdings for funds within a specific period"""
        # Implementation to update holdings based on latest CAS data
        pass
    
    def _update_all_holdings_from_cas(self, user, result: Dict):
        """Update all holdings based on CAS data"""
        # Implementation to update all holdings from CAS
        pass
    
    def generate_cas_via_kfintech(self, pan: str, email: str = None) -> Dict:
        """
        Generate CAS via KFintech (sends to registered email)
        
        Args:
            pan: PAN number of the investor
            email: Email address (optional, uses registered email if not provided)
            
        Returns:
            Dict with API response
        """
        try:
            url = f"{self.base_url}/v4/kfintech/generate"
            headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
            
            # Use sandbox mode if enabled
            if self.sandbox_mode:
                headers["x-api-key"] = "sandbox-with-json-responses"
                logger.info("Using CAS Parser sandbox mode for KFintech generate")
            
            data = {"pan": pan}
            # Email is required for KFintech generate
            if not email:
                return {"success": False, "error": "Email is required for KFintech CAS generation"}
            data["email"] = email
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            # Log response for debugging
            logger.info(f"KFintech API Response Status: {response.status_code}")
            logger.info(f"KFintech API Response: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            # Check for errors
            if result.get("status") == "failed":
                error_msg = result.get('msg', 'Unknown error')
                logger.error(f"KFintech CAS generation failed: {error_msg}")
                return {"success": False, "error": error_msg}
            
            logger.info(f"KFintech CAS generation initiated for PAN: {pan}")
            return {
                "success": True,
                "message": "CAS will be sent to your registered email within minutes",
                "response": result
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"KFintech CAS generation API error: {e}")
    def process_cas_download_response(self, cas_data: Dict, user) -> CASImport:
        """
        Process downloaded CAS data (from KFintech or CDSL) and create import record
        
        Args:
            cas_data: Parsed CAS data from API
            user: User object
            
        Returns:
            CASImport object
        """
        # Create CAS import record
        cas_import = CASImport.objects.create(
            user=user,
            filename=f"CAS-Download-{date.today().strftime('%Y%m%d')}.pdf",
            file_size=0,  # We don't have the actual file
            status='PROCESSING'
        )
        
        try:
            cas_import.mark_started()
            
            # Store parser response
            cas_import.parser_response = cas_data
            
            # Extract basic information
            self._extract_basic_info(cas_import, cas_data)
            
            # Process mutual funds data
            self._process_mutual_funds(cas_import, cas_data, user)
            
            # Mark as completed
            cas_import.mark_completed(success=True)
            
            logger.info(f"Successfully processed downloaded CAS for user {user.username}")
            
        except Exception as e:
            error_msg = f"Processing failed: {str(e)}"
            logger.error(f"Downloaded CAS processing error: {error_msg}")
            cas_import.mark_completed(success=False, error_message=error_msg)
        
        return cas_import


# Singleton instance
cas_parser_service = CASParserService()
