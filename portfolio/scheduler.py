"""
APScheduler background jobs for NAV refresh and factsheet fetch.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings

logger = logging.getLogger(__name__)
_scheduler = None


def nav_refresh_job():
    from funds.services import refresh_all_navs
    logger.info("Scheduled: Starting NAV refresh...")
    try:
        success, errors = refresh_all_navs()
        logger.info(f"Scheduled NAV refresh done: {success} ok, {errors} errors")
    except Exception as e:
        logger.error(f"NAV refresh job failed: {e}")


def factsheet_refresh_job():
    from factsheets.fetcher import run_monthly_factsheet_refresh
    logger.info("Scheduled: Starting monthly factsheet refresh...")
    try:
        log = run_monthly_factsheet_refresh()
        logger.info(f"Factsheet refresh done: {log.funds_processed} processed, {log.errors} errors")
    except Exception as e:
        logger.error(f"Factsheet refresh job failed: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone='Asia/Kolkata')

    # Daily NAV refresh
    _scheduler.add_job(
        nav_refresh_job,
        CronTrigger(hour=settings.NAV_REFRESH_HOUR, minute=0),
        id='nav_refresh',
        replace_existing=True,
    )

    # Monthly factsheet refresh (1st of each month)
    _scheduler.add_job(
        factsheet_refresh_job,
        CronTrigger(day=settings.FACTSHEET_REFRESH_DAY, hour=settings.FACTSHEET_REFRESH_HOUR, minute=0),
        id='factsheet_refresh',
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started.")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler stopped.")
