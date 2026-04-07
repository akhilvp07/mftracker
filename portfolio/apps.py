from django.apps import AppConfig


class PortfolioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'portfolio'

    def ready(self):
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            return
        try:
            from portfolio.scheduler import start_scheduler
            start_scheduler()
            
            # Seed fund database if empty
            self.seed_if_needed()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler start failed: {e}")
    
    def seed_if_needed(self):
        """Seed fund database if it's empty or has no funds."""
        import logging
        from funds.models import MutualFund, SeedStatus
        
        logger = logging.getLogger(__name__)
        
        # Check if we have any funds
        fund_count = MutualFund.objects.count()
        if fund_count > 0:
            logger.info(f"Database already has {fund_count} funds. Skipping seed.")
            return
        
        # Check if seeding is already in progress
        try:
            seed_status = SeedStatus.objects.get(pk=1)
            if seed_status.status == 'running':
                logger.info("Seeding already in progress. Skipping.")
                return
        except SeedStatus.DoesNotExist:
            seed_status = SeedStatus.objects.create(pk=1)
        
        logger.info("Database is empty. Starting automatic seed...")
        try:
            from funds.services import seed_fund_database
            result = seed_fund_database(force=True)
            if result.status == 'done':
                logger.info(f"Automatic seed completed: {result.total_funds} funds seeded.")
            else:
                logger.error(f"Automatic seed failed: {result.error_message}")
        except Exception as e:
            logger.error(f"Automatic seed failed: {e}")
