from urllib.parse import urlparse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from app.local_settings import firestore_creds
from datetime import datetime

def get_base_domain(url):
    """Extract base domain from URL"""
    parsed = urlparse(url)
    return parsed.netloc


def connect_to_sheets(spreadsheet_id):
    """Connect to Google Sheets API and return the service"""
    credentials = service_account.Credentials.from_service_account_info(
        firestore_creds, scopes=['https://www.googleapis.com/auth/spreadsheets']  # Updated scope to allow writing
    )
    
    service = build('sheets', 'v4', credentials=credentials)
    return service


def get_sheet_data(service, spreadsheet_id, range_name):
    """Fetch data from specified sheet and range"""
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()
    
    return result.get('values', [])



def write_to_sources_sheet(service, spreadsheet_id, new_results):
    """Update or append results to the sources sheet"""
    # Filter out results without URLs
    new_results = [result for result in new_results if result.get('url')]
    
    if not new_results:
        print("No valid sources to add (all missing URLs)")
        return
    
    # Get existing data
    existing_data = get_sheet_data(service, spreadsheet_id, 'sources!A:F')
    
    if not existing_data:
        # If sheet is empty, write headers and new results
        headers = ['Title', 'URL', 'Description', 'Date Found', 'Status', 'Leads Found']
        rows = [headers]
        rows.extend([
            [
                result['title'],
                result['url'],
                result['description'],
                result['date_found'],
                result['status'],
                result.get('leads_found', '')
            ] for result in new_results
        ])
    else:
        # Keep headers
        rows = [existing_data[0]]
        
        # Create a map of existing URLs to their row index, safely handling malformed rows
        url_index = existing_data[0].index('URL')
        url_to_index = {}
        for i, row in enumerate(existing_data[1:], 1):
            # Only include rows that have enough columns and a valid URL
            if len(row) > url_index and row[url_index]:
                url_to_index[row[url_index]] = i
        
        # Start with existing data, padding any short rows
        rows.extend([
            row + [''] * (len(existing_data[0]) - len(row)) if len(row) < len(existing_data[0]) else row
            for row in existing_data[1:]
        ])
        
        # Update or append each result
        for result in new_results:
            new_row = [
                result['title'],
                result['url'],
                result['description'],
                result['date_found'],
                result['status'],
                result.get('leads_found', '')
            ]
            
            if result['url'] in url_to_index:
                # Update existing row
                rows[url_to_index[result['url']]] = new_row
                print(f"Updated existing source: {result['url']}")
            else:
                # Append new row
                rows.append(new_row)
                print(f"Added new source: {result['url']}")
    
    # Prepare the request
    body = {
        'values': rows
    }
    
    try:
        # Update entire range with both existing and new data
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='sources!A1',
            valueInputOption='RAW',
            body=body
        ).execute()
        
        print(f"Successfully processed {len(new_results)} sources")
    except Exception as e:
        print(f"Error writing to sheet: {str(e)}")




def write_to_leads_sheet(service, spreadsheet_id, leads):
    """Write leads to the leads sheet, checking for domain duplicates"""
    # Get existing data to check for duplicates
    existing_data = get_sheet_data(service, spreadsheet_id, 'leads!A:E')
    
    if not existing_data:
        # Initialize sheet with headers if empty
        headers = ['Name', 'URL', 'Phone', 'Email', 'Notes']
        existing_data = [headers]
        existing_domains = set()
    else:
        # Get existing base domains from URL column
        url_index = 1  # URL is second column
        existing_domains = {
            row[url_index] for row in existing_data[1:]
            if len(row) > url_index and row[url_index]
        }
    
    # Filter out leads without URLs and deduplicate by domain
    new_leads = []
    for lead in leads:
        if not lead.get('url'):
            continue
            
        base_domain = get_base_domain(lead['url'])
        if base_domain not in existing_domains:
            existing_domains.add(base_domain)
            new_leads.append({
                **lead,
                'base_domain': base_domain
            })
    
    if not new_leads:
        print("No new unique leads to add")
        return
    
    # Prepare the rows
    rows = []
    for lead in new_leads:
        rows.append([
            lead.get('name', ''),
            lead['base_domain'],  # Use base domain as the URL
            lead.get('phone', ''),
            lead.get('email', ''),
            ''  # Notes (empty as requested)
        ])
    
    try:
        # Append new data
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'leads!A{len(existing_data) + 1}',
            valueInputOption='RAW',
            body={'values': rows}
        ).execute()
        
        print(f"Added {len(rows)} new unique leads to sheet")
        if len(leads) - len(new_leads) > 0:
            print(f"Skipped {len(leads) - len(new_leads)} duplicate leads")
    except Exception as e:
        print(f"Error writing to leads sheet: {str(e)}")


def get_existing_urls(service, spreadsheet_id):
    """Get list of URLs that already exist in the sources sheet"""
    existing_data = get_sheet_data(service, spreadsheet_id, 'sources!A:E')
    if not existing_data:
        return set()
    
    # Find URL column index (should be B based on headers)
    headers = existing_data[0]
    url_index = headers.index('URL')
    
    # Get all existing URLs
    existing_urls = {row[url_index] for row in existing_data[1:] if len(row) > url_index}
    return existing_urls


def write_to_searches_sheet(service, spreadsheet_id, query, num_results):
    """Log the search query and its results to the searches sheet"""
    # Get current date
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # Get existing data
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='searches!A:C'
        ).execute()
        existing_rows = result.get('values', [])
        
        if not existing_rows:
            # If sheet is empty, add headers first
            headers = [['Date', 'Query', 'Returns']]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='searches!A1',
                valueInputOption='RAW',
                body={'values': headers}
            ).execute()
            # Add new row after headers
            new_row = [[current_date, query, num_results]]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='searches!A2',
                valueInputOption='RAW',
                body={'values': new_row}
            ).execute()
            print(f"Created new sheet and logged search query with {num_results} results")
            return
        
        # Find if query exists (case-insensitive comparison)
        query_lower = query.lower()
        query_row_index = None
        for i, row in enumerate(existing_rows[1:], 1):  # Skip header row
            if len(row) >= 2 and row[1].lower() == query_lower:
                query_row_index = i
                break
        
        if query_row_index is not None:
            # Update existing row
            update_row = [[current_date, query, num_results]]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f'searches!A{query_row_index + 1}',  # +1 for 1-based index
                valueInputOption='RAW',
                body={'values': update_row}
            ).execute()
            print(f"Updated existing search query with {num_results} results")
        else:
            # Append new row
            new_row = [[current_date, query, num_results]]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f'searches!A{len(existing_rows) + 1}',
                valueInputOption='RAW',
                body={'values': new_row}
            ).execute()
            print(f"Added new search query with {num_results} results")
        
    except Exception as e:
        print(f"Error writing to searches sheet: {str(e)}")
        # If sheet doesn't exist, create it and try again
        try:
            # Create the sheet
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': 'searches'
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            # Write headers and new row
            rows = [
                ['Date', 'Query', 'Returns'],
                [current_date, query, num_results]
            ]
            
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='searches!A1',
                valueInputOption='RAW',
                body={'values': rows}
            ).execute()
            
            print(f"Created new sheet and logged search query with {num_results} results")
        except Exception as create_error:
            print(f"Error creating searches sheet: {str(create_error)}")




def write_to_suggested_searches_sheet(service, spreadsheet_id, queries):
    """Write suggested search queries to a new sheet"""
    # Get current date
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Prepare the rows with headers if needed
    try:
        # Check if sheet exists and get existing data
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='searches!A:C'
        ).execute()
        existing_rows = result.get('values', [])
        
        if not existing_rows:
            # If sheet is empty, add headers first
            rows = [['Date Generated', 'Suggested Query', 'Status']]
        else:
            rows = []
        
        # Add new queries
        for query in queries:
            rows.append([current_date, query, 'new'])
        
        if not existing_rows:
            # If sheet was empty, write everything including headers
            range_name = 'searches!A1'
        else:
            # Append to existing data
            range_name = f'searches!A{len(existing_rows) + 1}'
        
        # Write to sheet
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body={'values': rows}
        ).execute()
        
        print(f"Successfully wrote {len(queries)} suggested queries to sheet")
    except Exception as e:
        print(f"Error writing to suggested searches sheet: {str(e)}")
        # If sheet doesn't exist, create it and try again
        try:
            # Create the sheet
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': 'searches'
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            # Try writing again with headers
            rows = [['Date Generated', 'Suggested Query', 'Status']]
            for query in queries:
                rows.append([current_date, query, 'new'])
            
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='searches!A1',
                valueInputOption='RAW',
                body={'values': rows}
            ).execute()
            
            print(f"Created new sheet and wrote {len(queries)} suggested queries")
        except Exception as create_error:
            print(f"Error creating suggested searches sheet: {str(create_error)}")


def create_new_spreadsheet(service, title, email_to_share):
    """Create a new spreadsheet with required sheets and share it with the given email"""
    try:
        # Get credentials for both services
        credentials = service_account.Credentials.from_service_account_info(
            firestore_creds, 
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.file'  # Added Drive scope
            ]
        )
        
        # Create services with proper credentials
        sheets_service = build('sheets', 'v4', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # Create the spreadsheet
        spreadsheet = sheets_service.spreadsheets().create(
            body={
                'properties': {'title': title},
                'sheets': [
                    {'properties': {'title': 'sources'}},
                    {'properties': {'title': 'leads'}},
                    {'properties': {'title': 'searches'}}
                ]
            }
        ).execute()
        
        spreadsheet_id = spreadsheet['spreadsheetId']
        
        # Initialize sources sheet
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='sources!A1',
            valueInputOption='RAW',
            body={'values': [['Title', 'URL', 'Description', 'Date Found', 'Status', 'Leads Found']]}
        ).execute()
        
        # Initialize leads sheet
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='leads!A1',
            valueInputOption='RAW',
            body={'values': [['Name', 'URL', 'Phone', 'Email', 'Notes']]}
        ).execute()
        
        # Initialize searches sheet
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='searches!A1',
            valueInputOption='RAW',
            body={'values': [['Date', 'Query', 'Returns']]}
        ).execute()
        
        # Share the spreadsheet
        drive_service.permissions().create(
            fileId=spreadsheet_id,
            body={
                'type': 'user',
                'role': 'writer',
                'emailAddress': email_to_share
            }
        ).execute()
        
        return spreadsheet_id
    except Exception as e:
        print(f"Error creating spreadsheet: {str(e)}")
        return None


def get_spreadsheet_metadata(service, spreadsheet_id):
    """Get the spreadsheet title and URL"""
    try:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        
        return {
            'title': spreadsheet['properties']['title'],
            'url': f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        }
    except Exception as e:
        print(f"Error getting spreadsheet metadata: {str(e)}")
        return None
