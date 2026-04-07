"""
Base classes for factsheet fetchers
"""
import logging
from datetime import date
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when fetching fails"""
    pass


class FactsheetFetcher:
    """Base class for factsheet fetchers"""
    
    def fetch(self, fund, month: date) -> Dict[str, Any]:
        """Fetch fund factsheet data"""
        raise NotImplementedError
    
    def get_name(self) -> str:
        """Get fetcher name"""
        return self.__class__.__name__
