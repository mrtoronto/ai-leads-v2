import requests
from typing import List, Dict, Tuple
import logging
from datetime import datetime, timedelta
import re
from pathlib import Path
from app.local_settings import (
    OPENAI_API_KEY_GPT4,
    firestore_creds
)

from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.core.email_utils import (
    normalize_url,
    analyze_website_content,
    select_email_template,
    customize_template,
    refine_template_customization,
    create_customized_email,
    analyze_website_content_with_notes,
    customize_template_with_notes
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from app.core.models import (
    WebsiteAnalysis, 
    TemplateSelection, 
    TemplateCustomization, 
    website_analysis_adapter, 
    template_selection_adapter, 
    template_customization_adapter
)

from app.llm.email_template import EMAIL_TEMPLATES, get_email_content, ZAKAYA_CONTEXT
from app.llm.prompts import WRITE_EMAIL_PROMPT, REFINE_EMAIL_PROMPT
from app.llm.llm import _llm

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

def parse_contact_list(contact_list: str) -> List[Tuple[str, str]]:
    """
    Parse the contact list string into a list of (website, email) tuples
    
    Args:
        contact_list: String with website and email on each line, tab-separated
        
    Returns:
        List of (website, email) tuples
    """
    contacts = []
    for line in contact_list.strip().split('\n'):
        if line.strip():  # Skip empty lines
            website, email = line.strip().split('\t')
            contacts.append((normalize_url(website), email))
    return contacts

def update_lead_emailed_status(service, spreadsheet_id, email):
    """Update the Emailed? column to True for all rows with matching email"""
    # Get existing data
    existing_data = get_sheet_data(service, spreadsheet_id, 'leads!A:L')
    if not existing_data:
        print("No data found in leads sheet")
        return
    
    # Get header row and find email column index
    headers = existing_data[0]
    try:
        email_index = headers.index('Email')
        emailed_index = headers.index('Emailed?')
    except ValueError:
        print("Could not find Email or Emailed? columns in leads sheet")
        return
    
    # Update rows with matching email
    rows_updated = 0
    for i, row in enumerate(existing_data[1:], 1):  # Skip header row
        # Ensure row has enough columns
        while len(row) < len(headers):
            row.append('')
            
        if row[email_index] == email:
            row[emailed_index] = 'True'
            rows_updated += 1
    
    if rows_updated > 0:
        # Write back all data
        body = {
            'values': existing_data
        }
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='leads!A1',
            valueInputOption='RAW',
            body=body
        ).execute()
        print(f"Updated {rows_updated} rows for email {email}")
    else:
        print(f"No matching rows found for email {email}")

def check_if_already_emailed(service, spreadsheet_id, email):
    """Check if an email address has already been emailed
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: ID of the spreadsheet
        email: Email address to check
        
    Returns:
        bool: True if already emailed, False otherwise
    """
    # Get existing data
    existing_data = get_sheet_data(service, spreadsheet_id, 'leads!A:L')
    if not existing_data:
        print("No data found in leads sheet")
        return False
    
    # Get header row and find email column index
    headers = existing_data[0]
    try:
        email_index = headers.index('Email')
        emailed_index = headers.index('Emailed?')
    except ValueError:
        print("Could not find Email or Emailed? columns in leads sheet")
        return False
    
    already_emailed = False
    needs_update = False
    
    # First check if any instance of the email has been marked as emailed
    for row in existing_data[1:]:  # Skip header row
        if len(row) > email_index and row[email_index] == email:
            if len(row) > emailed_index and row[emailed_index].strip() != "":
                already_emailed = True
                break
    
    # If already emailed, make sure ALL instances of this email are marked as emailed
    if already_emailed:
        rows_updated = 0
        for row in existing_data[1:]:  # Skip header row
            if len(row) > email_index and row[email_index] == email:
                # Ensure row has enough columns
                while len(row) < len(headers):
                    row.append('')
                
                if len(row) > emailed_index and row[emailed_index] != 'True':
                    row[emailed_index] = 'True'
                    rows_updated += 1
                    needs_update = True
        
        # If we found rows that need updating, write back the data
        if needs_update:
            body = {
                'values': existing_data
            }
            service.spreadsheets().values().update(
                spreadsheet_id=spreadsheet_id,
                range='leads!A1',
                valueInputOption='RAW',
                body=body
            ).execute()
            print(f"Updated {rows_updated} additional rows for email {email} to maintain consistency")
    
    return already_emailed
