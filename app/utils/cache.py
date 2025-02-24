import os
import json
from pathlib import Path

def get_cache_dir():
    """Get the cache directory path, creating it if it doesn't exist."""
    cache_dir = Path.home() / '.zakaya' / 'ai-leads'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def get_spreadsheet_id_from_cache():
    """Read the spreadsheet ID from the cache file."""
    cache_file = get_cache_dir() / 'spreadsheet_id.txt'
    try:
        if cache_file.exists():
            return cache_file.read_text().strip()
    except Exception:
        pass
    return None

def save_spreadsheet_id_to_cache(spreadsheet_id):
    """Save the spreadsheet ID to the cache file."""
    if not spreadsheet_id:
        return
        
    cache_file = get_cache_dir() / 'spreadsheet_id.txt'
    try:
        cache_file.write_text(spreadsheet_id)
    except Exception:
        pass  # Silently fail if we can't write to cache 