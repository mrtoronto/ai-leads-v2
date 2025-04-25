import streamlit as st
import pandas as pd
import time
from typing import Dict, List, Any, Optional

def initialize_sheet_cache():
    """Initialize the cache structure in session state if it doesn't exist"""
    if 'sheet_cache' not in st.session_state:
        st.session_state.sheet_cache = {
            'data': {},  # Sheet data keyed by sheet name
            'last_updated': {},  # Timestamp of last update for each sheet
            'metadata': None,  # Spreadsheet metadata
        }
    
    if 'cache_initialized' not in st.session_state:
        st.session_state.cache_initialized = False

def is_cache_valid(sheet_name: str, max_age_seconds: int = 300) -> bool:
    """Check if cache for a specific sheet is valid (not expired)"""
    if 'sheet_cache' not in st.session_state:
        return False
        
    if sheet_name not in st.session_state.sheet_cache['last_updated']:
        return False
        
    # Check if cache is expired
    last_updated = st.session_state.sheet_cache['last_updated'][sheet_name]
    current_time = time.time()
    return (current_time - last_updated) <= max_age_seconds

def get_sheet_data_cached(service, spreadsheet_id: str, sheet_name: str, 
                         force_refresh: bool = False) -> pd.DataFrame:
    """Get sheet data from cache or from API if cache is invalid"""
    initialize_sheet_cache()
    
    # Return from cache if valid and refresh not forced
    if not force_refresh and is_cache_valid(sheet_name):
        return st.session_state.sheet_cache['data'].get(sheet_name)
    
    # Fetch data from API
    try:
        range_name = f'{sheet_name}!A:Z'  # Use a wider range
        response = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        values = response.get('values', [])
        
        if len(values) > 0:
            # Convert to DataFrame
            headers = values[0]
            data = values[1:] if len(values) > 1 else []
            
            # Ensure all rows have the same length as headers
            normalized_data = []
            for row in data:
                if len(row) < len(headers):
                    normalized_data.append(row + [''] * (len(headers) - len(row)))
                else:
                    normalized_data.append(row)
                    
            df = pd.DataFrame(normalized_data, columns=headers)
            
            # Update cache
            st.session_state.sheet_cache['data'][sheet_name] = df
            st.session_state.sheet_cache['last_updated'][sheet_name] = time.time()
            
            return df
        else:
            # Empty sheet, return empty DataFrame with same structure
            empty_df = pd.DataFrame(columns=[])
            st.session_state.sheet_cache['data'][sheet_name] = empty_df
            st.session_state.sheet_cache['last_updated'][sheet_name] = time.time()
            return empty_df
            
    except Exception as e:
        st.error(f"Error fetching sheet data for '{sheet_name}': {str(e)}")
        return None

def update_cache_after_write(sheet_name: str, updated_data: pd.DataFrame):
    """Update cache after a write operation"""
    initialize_sheet_cache()
    
    # Update the cache with new data
    st.session_state.sheet_cache['data'][sheet_name] = updated_data
    st.session_state.sheet_cache['last_updated'][sheet_name] = time.time()

def clear_cache():
    """Clear all cached data"""
    if 'sheet_cache' in st.session_state:
        st.session_state.sheet_cache = {
            'data': {},
            'last_updated': {},
            'metadata': None
        }
    
    st.session_state.cache_initialized = False

def get_cache_info() -> Dict:
    """Get information about the current cache state"""
    if 'sheet_cache' not in st.session_state:
        return {
            'initialized': False,
            'sheets_cached': 0,
            'oldest_cache': None,
            'newest_cache': None
        }
    
    sheets_cached = len(st.session_state.sheet_cache['data'])
    
    timestamps = list(st.session_state.sheet_cache['last_updated'].values())
    oldest_cache = min(timestamps) if timestamps else None
    newest_cache = max(timestamps) if timestamps else None
    
    # Convert to relative time
    current_time = time.time()
    if oldest_cache:
        oldest_cache = format_time_ago(current_time - oldest_cache)
    if newest_cache:
        newest_cache = format_time_ago(current_time - newest_cache)
    
    return {
        'initialized': st.session_state.get('cache_initialized', False),
        'sheets_cached': sheets_cached,
        'oldest_cache': oldest_cache,
        'newest_cache': newest_cache,
        'sheet_names': list(st.session_state.sheet_cache['data'].keys())
    }

def format_time_ago(seconds: float) -> str:
    """Format time difference in seconds to a human-readable string"""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds/60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds/3600)}h ago"
    else:
        return f"{int(seconds/86400)}d ago"

def load_all_sheets(service, spreadsheet_id: str, force_refresh: bool = False):
    """Load all important sheets into cache"""
    if not spreadsheet_id:
        return
        
    initialize_sheet_cache()
    
    # Common sheets to cache
    sheets_to_cache = ['searches', 'sources', 'leads']
    
    for sheet_name in sheets_to_cache:
        get_sheet_data_cached(service, spreadsheet_id, sheet_name, force_refresh)
    
    # Mark as initialized
    st.session_state.cache_initialized = True
    
    # Cache the metadata too
    if force_refresh or not st.session_state.sheet_cache['metadata']:
        try:
            metadata = service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            st.session_state.sheet_cache['metadata'] = metadata
        except Exception as e:
            st.error(f"Error fetching spreadsheet metadata: {str(e)}") 