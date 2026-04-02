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
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler start failed: {e}")
