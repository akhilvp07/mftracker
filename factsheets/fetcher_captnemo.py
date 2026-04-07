"""
Captnemo API fetcher for enriched mutual fund data
"""
import logging
import requests
from datetime import date
from typing import Dict, Any, Optional
from .fetcher_base import FactsheetFetcher, FetchError

logger = logging.getLogger(__name__)

CAPTNEMO_API_BASE = "https://mf.captnemo.in/kuvera"


class CaptnemoFetcher(FactsheetFetcher):
    """
    Enriched fetcher using Captnemo API (mf.captnemo.in)
    Provides comprehensive fund data including AUM, expense ratio, fund manager, etc.
    """
    
    def fetch(self, fund, month: date) -> Dict[str, Any]:
        """Fetch fund factsheet from Captnemo API"""
        if not fund.isin:
            logger.warning(f"No ISIN for fund {fund.scheme_name}, skipping Captnemo fetch")
            return self._empty_result()
        
        url = f"{CAPTNEMO_API_BASE}/{fund.isin}"
        
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            if not data:
                logger.warning(f"No data from Captnemo for {fund.isin}")
                return self._empty_result()
            
            # Parse first result (API returns array)
            fund_data = data[0] if isinstance(data, list) and data else data
            
            return self._parse_captnemo_data(fund_data)
            
        except requests.RequestException as e:
            logger.error(f"Captnemo API error for {fund.isin}: {e}")
            raise FetchError(f"Failed to fetch from Captnemo: {e}")
        except (ValueError, KeyError, IndexError) as e:
            logger.error(f"Error parsing Captnemo data for {fund.isin}: {e}")
            return self._empty_result()
    
    def _parse_captnemo_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Captnemo API response"""
        result = self._empty_result()
        
        # Basic fund info
        result["fund_manager"] = data.get("fund_manager", "")
        result["amc"] = data.get("fund_house", "").replace("_MF", " Mutual Fund")
        result["category"] = data.get("fund_category", "")
        result["scheme_type"] = data.get("fund_type", "")
        result["objective"] = data.get("investment_objective", "")
        
        # AUM in crores
        aum = data.get("aum")
        if aum is not None:
            try:
                result["aum"] = float(aum)
            except (ValueError, TypeError):
                result["aum"] = None
        else:
            result["aum"] = None
        
        # Expense ratio
        expense_ratio = data.get("expense_ratio")
        if expense_ratio is not None:
            try:
                result["expense_ratio"] = float(expense_ratio)
            except (ValueError, TypeError):
                result["expense_ratio"] = None
        else:
            result["expense_ratio"] = None
        
        # NAV data
        nav_data = data.get("nav", {})
        if nav_data:
            result["nav"] = nav_data.get("nav")
            result["nav_date"] = nav_data.get("date")
        
        # Returns data (1 year, 3 year, 5 year)
        returns = data.get("returns", {})
        if returns:
            result["returns_1yr"] = returns.get("year_1")
            result["returns_3yr"] = returns.get("year_3")
            result["returns_5yr"] = returns.get("year_5")
        
        # Risk rating
        result["risk_rating"] = data.get("crisil_rating", "")
        
        # Additional metadata
        result["fund_code"] = data.get("code", "")
        result["plan"] = data.get("plan", "")
        result["face_value"] = data.get("face_value")
        result["lock_in_period"] = data.get("lock_in_period", 0)
        result["maturity_type"] = data.get("maturity_type", "")
        result["start_date"] = data.get("start_date")
        
        # Holdings and sectors are not provided by Captnemo API
        # and we're not displaying them in the dashboard anymore
        result["holdings"] = []
        result["sectors"] = []
        result["fetch_error"] = None
        
        return result
    
    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure"""
        return {
            "fund_manager": "",
            "amc": "",
            "category": "",
            "scheme_type": "",
            "objective": "",
            "aum": None,
            "expense_ratio": None,
            "nav": None,
            "nav_date": None,
            "returns_1yr": None,
            "returns_3yr": None,
            "returns_5yr": None,
            "risk_rating": "",
            "fund_code": "",
            "plan": "",
            "face_value": None,
            "lock_in_period": 0,
            "maturity_type": "",
            "start_date": None,
            "holdings": [],
            "sectors": [],
            "fetch_error": None,
        }
