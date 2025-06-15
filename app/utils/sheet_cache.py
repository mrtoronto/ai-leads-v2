import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import pandas as pd
from app.utils.gcs import get_sheet_data

logger = logging.getLogger(__name__)

# Module-level cache to replace st.session_state
_sheet_cache = {}

def get_sheet_data_cached(service, spreadsheet_id: str, sheet_name: str) -> Optional[pd.DataFrame]:
    """Get sheet data from cache or fetch if not cached"""
    cache_key = f"{spreadsheet_id}_{sheet_name}"
    
    if cache_key in _sheet_cache:
        logger.info(f"Using cached data for {sheet_name}")
        return _sheet_cache[cache_key]['data']
    
    # If not in cache, fetch from API
    logger.info(f"Fetching fresh data for {sheet_name}")
    try:
        raw_data = get_sheet_data(service, spreadsheet_id, f'{sheet_name}!A:Z')
        if raw_data and len(raw_data) > 1:
            headers = raw_data[0]
            data_rows = raw_data[1:]
            df = pd.DataFrame(data_rows, columns=headers)
            
            # Cache the data
            _sheet_cache[cache_key] = {
                'data': df,
                'timestamp': datetime.now(),
                'sheet_name': sheet_name
            }
            
            return df
        else:
            logger.warning(f"No data found for {sheet_name}")
            return None
    except Exception as e:
        logger.error(f"Error fetching data for {sheet_name}: {str(e)}")
        return None

def update_cache_after_write(spreadsheet_id: str, sheet_name: str):
    """Mark cache as stale after a write operation"""
    cache_key = f"{spreadsheet_id}_{sheet_name}"
    if cache_key in _sheet_cache:
        del _sheet_cache[cache_key]
        logger.info(f"Cleared cache for {sheet_name} after write operation")

def clear_cache():
    """Clear all cached data"""
    global _sheet_cache
    _sheet_cache = {}
    logger.info("Cleared all sheet cache")

def get_cache_info() -> Dict[str, Any]:
    """Get information about the current cache state"""
    if not _sheet_cache:
        return {
            'initialized': False,
            'sheets_cached': 0,
            'sheet_names': [],
            'newest_cache': None
        }
    
    sheet_names = [cache_data['sheet_name'] for cache_data in _sheet_cache.values()]
    timestamps = [cache_data['timestamp'] for cache_data in _sheet_cache.values()]
    newest_timestamp = max(timestamps) if timestamps else None
    
    return {
        'initialized': True,
        'sheets_cached': len(_sheet_cache),
        'sheet_names': sheet_names,
        'newest_cache': newest_timestamp.strftime('%Y-%m-%d %H:%M:%S') if newest_timestamp else None
    }

def load_all_sheets(service, spreadsheet_id: str, force_refresh: bool = False):
    """Load all common sheets into cache"""
    sheet_names = ['searches', 'sources', 'leads']
    
    if force_refresh:
        clear_cache()
    
    for sheet_name in sheet_names:
        try:
            get_sheet_data_cached(service, spreadsheet_id, sheet_name)
        except Exception as e:
            logger.error(f"Failed to load {sheet_name}: {str(e)}")
    
    logger.info(f"Loaded {len(sheet_names)} sheets into cache") 