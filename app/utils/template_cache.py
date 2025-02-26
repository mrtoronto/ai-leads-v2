import json
import os
from pathlib import Path

# Path for cached templates
CACHE_DIR = Path("app/cache")
TEMPLATES_CACHE_FILE = CACHE_DIR / "email_templates.json"

def ensure_cache_dir():
    """Ensure the cache directory exists"""
    os.makedirs(CACHE_DIR, exist_ok=True)

def save_templates_to_cache(templates_data):
    """
    Save email templates and context to cache file
    
    Args:
        templates_data: Dictionary with template data and optional 'context' key
    """
    ensure_cache_dir()
    with open(TEMPLATES_CACHE_FILE, 'w') as f:
        json.dump(templates_data, f, indent=2)

def load_templates_from_cache():
    """
    Load templates from cache file if it exists
    
    Returns:
        Dictionary with templates and context, or None if cache doesn't exist
    """
    if not TEMPLATES_CACHE_FILE.exists():
        return None
    
    try:
        with open(TEMPLATES_CACHE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupted or can't be read, return None
        return None 