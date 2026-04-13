# Captnemo API Notes

## Overview
Captnemo API (mf.captnemo.in) was previously used as an enriched data source for mutual fund factsheets.

## API Details
- **Base URL**: `https://mf.captnemo.in/kuvera`
- **Endpoint**: `/{ISIN}`
- **Authentication**: None required (free API)
- **Response Format**: JSON array

## Data Provided
- Fund Manager name
- AUM (Assets Under Management)
- Expense Ratio
- Fund category and type
- Other enriched metadata

## Implementation Notes
```python
class CaptnemoFetcher(FactsheetFetcher):
    def fetch(self, fund, month: date) -> Dict[str, Any]:
        if not fund.isin:
            return self._empty_result()
        
        url = f"{CAPTNEMO_API_BASE}/{fund.isin}"
        response = requests.get(url, timeout=15)
        data = response.json()
        
        # Parse first result (API returns array)
        fund_data = data[0] if isinstance(data, list) and data else data
        return self._parse_captnemo_data(fund_data)
```

## Why It Was Removed
1. AMFI portfolio pages started returning 404 errors
2. mfdata.in provides similar data more reliably
3. Wanted to reduce dependency on multiple APIs
4. MFADataFetcher approach using existing data was more stable

## Future Considerations
If Captnemo API is needed in future:
1. Check API availability and reliability
2. Compare data quality with mfdata.in
3. Consider rate limits and usage policies
4. May be useful for funds not available on mfdata.in

## Files Removed (but backed up here):
- `factsheets/fetcher_captnemo.py` - Complete implementation
- Registry mappings for "captnemo" fetcher

## Removal Date
April 13, 2026 - Removed due to AMFI 404 issues and switch to mfdata.in
