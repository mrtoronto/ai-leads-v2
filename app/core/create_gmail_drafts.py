import base64
import streamlit as st
import requests
from typing import List, Dict, Tuple, Optional, Any
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import datetime
import asyncio
import aiohttp
from pathlib import Path
import os
import sys
import random
import time
import re

# --- Configuration ---
# Maximum number of concurrent tasks (website fetching, email creation)
MAX_CONCURRENT_WORKERS = 10
# ---

# Ensure PyJWT and cryptography are installed
try:
    import jwt
    # Test if we have cryptography by attempting to use RS256
    try:
        jwt.encode({"test": "payload"}, "test-key", algorithm="RS256")
    except Exception as e:
        if "Algorithm 'RS256' could not be found" in str(e):
            st.error("Cryptography package is required. Installing now...")
            import subprocess
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
                st.success("Cryptography package installed successfully!")
            except Exception as e:
                st.error(f"Failed to install cryptography: {str(e)}")
                st.error("Please run 'pip install cryptography' manually and restart the application.")
                raise ImportError("Cryptography is required but could not be installed automatically")
except ImportError:
    # More robust error handling for PyJWT
    st.error("PyJWT package is required. Installing now...")
    import subprocess
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyJWT[crypto]"])
        import jwt
        st.success("PyJWT with crypto installed successfully!")
    except Exception as e:
        st.error(f"Failed to install PyJWT: {str(e)}")
        st.error("Please run 'pip install PyJWT[crypto]' manually and restart the application.")
        raise ImportError("PyJWT is required but could not be installed automatically")

# Ensure aiohttp is installed
try:
    import aiohttp
except ImportError:
    st.error("aiohttp package is required. Installing now...")
    import subprocess
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp"])
        import aiohttp
        st.success("aiohttp installed successfully!")
    except Exception as e:
        st.error(f"Failed to install aiohttp: {str(e)}")
        st.error("Please run 'pip install aiohttp' manually and restart the application.")
        raise ImportError("aiohttp is required but could not be installed automatically")

from app.local_settings import (
    OPENAI_API_KEY_GPT4,
    firestore_creds,
    GMAIL_USER_EMAIL
)

from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.utils.sheet_cache import get_sheet_data_cached, update_cache_after_write

from app.core.create_zoho_drafts import (
    normalize_url,
    analyze_website_content,
    select_email_template,
    customize_template,
    refine_template_customization,
    create_customized_email,
    update_lead_emailed_status,
    check_if_already_emailed
)

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')

def get_access_token(service_account_info: Dict, user_email: str) -> str:
    """
    Get an access token for Gmail API using direct JWT approach
    
    Args:
        service_account_info: Service account credentials as a dictionary
        user_email: Email to impersonate
        
    Returns:
        str: Access token
    """
    try:
        # Create JWT claims
        now = datetime.datetime.utcnow()
        
        # Create payload with CORRECT Gmail scopes for drafts
        payload = {
            'iss': service_account_info['client_email'],
            'sub': user_email,
            'scope': 'https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send',
            'aud': 'https://oauth2.googleapis.com/token',
            'iat': now,
            'exp': now + datetime.timedelta(minutes=60)  # Token valid for 1 hour
        }
        
        # Sign the JWT with the private key from service account
        private_key = service_account_info['private_key']
        token = jwt.encode(
            payload, 
            private_key, 
            algorithm='RS256'
        )
        
        # Exchange JWT for access token
        logging.info(f"Requesting access token for {user_email}")
        response = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': token
            }
        )
        
        # Check if the request was successful
        if response.status_code == 200:
            logging.info("Successfully obtained access token")
            return response.json()['access_token']
        else:
            logging.error(f"Error getting access token: {response.status_code} - {response.text}")
            raise Exception(f"Failed to get access token: {response.text}")
            
    except Exception as e:
        logging.error(f"Error creating access token: {str(e)}")
        raise

# Add a function to validate email addresses
def is_valid_email(email: str) -> bool:
    """
    Check if an email address is valid using regex pattern
    
    Args:
        email: Email address to validate
        
    Returns:
        bool: True if valid email format
    """
    if not email:
        return False
        
    # Basic email validation pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

# Update the is_transient_error function to better classify error types
def is_transient_error(error_message: str) -> bool:
    """
    Determine if an error is transient (temporary) or permanent
    
    Args:
        error_message: The error message to check
        
    Returns:
        bool: True if error is transient and should be retried
    """
    # Empty error messages should be treated as transient
    if not error_message or error_message.strip() == '':
        return True
        
    error_lower = error_message.lower()
    
    # List of errors that we know are permanent
    permanent_patterns = [
        'does not exist',
        'not found',
        'invalid email',
        'invalid to header',
        'domain not found',
        '404',
        'no such host',
        'ssl/tls alert handshake failure',  # Added: SSL handshake failures are permanent
        'sslv3_alert_handshake_failure',    # Added: Another form of SSL failure
        'port 443',                         # Added: Port 443 issues usually indicate broken HTTPS
        'certificate verify failed',        # Added: Bad certificates are usually permanent
        'hostname mismatch',                # Added: Hostname mismatches are permanent
        'certificate has expired',           # Added: Expired certificates are permanent
    ]
    
    # First check if it's explicitly a permanent error
    if any(pattern in error_lower for pattern in permanent_patterns):
        return False
        
    # List of errors that are definitely transient
    transient_patterns = [
        'connection reset',
        'connection refused', 
        'temporarily unavailable',
        'retry',
        'service unavailable',
        'unreachable',
        'timeout',
        'eof',
        'broken pipe',
        '500',
        '502',
        '503',
        '504'
    ]
    
    # Then check if it's a known transient error
    if any(pattern in error_lower for pattern in transient_patterns):
        return True
        
    # For DNS errors, do a more careful check
    if 'nodename nor servname provided' in error_lower:
        try:
            domain = error_lower.split('host ')[1].split(':')[0]
            import socket
            socket.gethostbyname(domain)
            return True
        except:
            return False
            
    # By default, treat unknown errors as transient
    return True

async def create_draft_with_http_async(session: aiohttp.ClientSession, access_token: str, 
                                  to_email: str, subject: str, content: str, from_email: str
                                  ) -> Tuple[bool, str]:
    """
    Create a draft email using direct HTTP requests to Gmail API (async version)
    Uses the provided aiohttp session.
    
    Args:
        session: aiohttp ClientSession (now used)
        access_token: Access token for Gmail API
        to_email: Recipient email
        subject: Email subject
        content: HTML content of email
        from_email: Sender email
        
    Returns:
        Tuple[bool, str]: (Success status, Error message if any)
    """
    error_msg = ""
    max_api_retries = 1 # Allow one retry specifically for API timeouts/5xx
    
    for attempt in range(max_api_retries + 1):
        try:
            # Validate email first
            if not is_valid_email(to_email):
                return False, f"Invalid email format: {to_email}"
            
            # Create email MIME message
            message = MIMEMultipart('alternative')
            message['to'] = to_email
            message['from'] = from_email
            message['subject'] = subject
            
            # Add HTML content
            html_part = MIMEText(content, 'html')
            message.attach(html_part)
            
            # Encode as base64
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Create draft using HTTP request
            url = 'https://gmail.googleapis.com/gmail/v1/users/me/drafts'
            # Use passed-in session's headers + add specific ones
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Draft request body
            body = {
                'message': {
                    'raw': raw_message
                }
            }
            
            # Make API request using the provided session
            # Use a specific timeout for the API call, longer than website fetch
            api_timeout = aiohttp.ClientTimeout(total=120) # Increased API timeout
            retry_suffix = f" (attempt {attempt+1}/{max_api_retries+1})" if attempt > 0 else ""
            logging.info(f"Creating draft email to {to_email}{retry_suffix}")
            
            async with session.post(url, headers=headers, json=body, timeout=api_timeout) as response:
                # Check if request was successful
                if response.status in (200, 201):
                    logging.info(f"Successfully created draft for {to_email}")
                    return True, ""
                else:
                    response_text = await response.text()
                    error_msg = f"Error creating draft: {response.status} - {response_text}"
                    logging.error(error_msg)
                    
                    # Check for auth errors (401)
                    if response.status == 401:
                        # Don't raise here, just return the error to be handled by process_contact
                        return False, f"TokenExpiredError: Gmail API token may have expired ({error_msg})"
                    
                    # Treat other non-success as failures for this attempt
                    # Only retry on 5xx server errors
                    if response.status >= 500 and attempt < max_api_retries:
                        error_msg = f"Received {response.status} from Gmail API, retrying..."
                        logging.warning(error_msg)
                        await asyncio.sleep(3 * (attempt + 1)) # Short delay before API retry
                        continue # Go to next attempt in the loop
                    else:
                        # Permanent client error or final attempt failed
                        return False, error_msg
                
        except TokenExpiredError as e: # Should not be raised anymore, but keep catch just in case
            logging.error(f"TokenExpiredError caught unexpectedly: {e}")
            return False, str(e)
        
        except asyncio.TimeoutError as e:
            error_msg = f"Timeout error connecting to Gmail API: {str(e)}"
            logging.error(error_msg)
            # Retry once on timeout
            if attempt < max_api_retries:
                await asyncio.sleep(3 * (attempt + 1))
                continue # Go to next attempt in the loop
            else:
                return False, error_msg # Final attempt timed out
            
        except Exception as e:
            error_msg = f"Error in create_draft_with_http_async: {str(e)}"
            logging.error(error_msg, exc_info=True) # Log full traceback
            return False, error_msg

    # If loop finishes without returning (shouldn't happen with retry logic)
    return False, f"Failed after {max_api_retries + 1} attempts: {error_msg}"

class ServiceAuthError(Exception):
    """Base class for service authentication errors"""
    pass

class TokenExpiredError(ServiceAuthError):
    """Raised when the Gmail API token has expired"""
    pass

class SheetsAuthError(ServiceAuthError):
    """Raised when the Sheets API authentication fails"""
    pass

async def refresh_sheets_service(spreadsheet_id: str) -> Any:
    """
    Create a fresh connection to Google Sheets
    
    Args:
        spreadsheet_id: ID of the spreadsheet
        
    Returns:
        service: Fresh Google Sheets service object
    """
    try:
        logging.info("Refreshing Sheets service connection...")
        service = connect_to_sheets(spreadsheet_id)
        
        # Test the connection with a simple request
        service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        
        logging.info("Successfully refreshed Sheets service connection")
        return service
    except Exception as e:
        logging.error(f"Failed to refresh Sheets service: {str(e)}")
        raise SheetsAuthError(f"Failed to refresh Sheets service: {str(e)}")

async def fetch_website_with_retries(session: aiohttp.ClientSession, url: str, max_retries: int = 0) -> Tuple[bool, str, str]:
    """
    Fetch website content with retries - simplified settings
    
    Args:
        session: aiohttp ClientSession
        url: Website URL to fetch
        max_retries: Maximum number of retry attempts (default 0 means 1 attempt total)
        
    Returns:
        Tuple[bool, str, str]: (Success status, Content if successful, Error message if not)
    """
    # Normalize website URL if needed
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    # Simple, reliable headers, mimicking a real browser more closely
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br', # Added br for Brotli
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1', # Common header
        'Sec-CH-UA': '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"', # Client Hints
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"macOS"',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-User': '?1',
        'Sec-Fetch-Dest': 'document',
    }
    
    last_error = ""
    
    for attempt in range(max_retries + 1): # +1 because max_retries is retries *after* first attempt
        try:
            attempt_suffix = f" (attempt {attempt+1}/{max_retries+1})" if max_retries > 0 else ""
            logging.info(f"Fetching website {url}{attempt_suffix}")
            
            # Simple timeout
            # timeout = aiohttp.ClientTimeout(total=45) # Increased timeout
            
            async with session.get(
                url,
                # Use the session's default timeout (currently 90s)
                # timeout=timeout, 
                verify_ssl=False, # Still allow sites with bad certs
                allow_redirects=True,
                headers=headers,
                raise_for_status=False # Don't raise for non-200 status codes
            ) as response:
                if response.status == 200:
                    # Handle potential encoding errors gracefully
                    content = await response.text(errors='replace')
                    if content and content.strip():
                        return True, content, ""
                    else:
                        # Treat empty content as a failure for this attempt
                        last_error = "Received empty content"
                        logging.warning(f"{url}: {last_error}")
                        
                elif response.status == 404:
                    last_error = "Page not found (404)"
                    logging.error(f"{url}: {last_error}")
                    return False, "", last_error # 404 is permanent, don't retry
                    
                else:
                    last_error = f"HTTP {response.status}"
                    logging.warning(f"{url}: {last_error}")
                    # Only retry for server errors (5xx) or potential transient issues
                    if response.status < 500 and response.status not in (408, 429): 
                        return False, "", last_error # Client errors are permanent

            # If we got here, it means we failed with status != 200 or got empty content
            # Check if we should retry
            if attempt < max_retries:
                await asyncio.sleep(2) # Simple fixed delay before retry
                continue
            else:
                # If all attempts failed
                return False, "", last_error

        except asyncio.TimeoutError:
            last_error = "Timeout error"
            logging.error(f"{url}: {last_error}")
            if attempt < max_retries:
                await asyncio.sleep(2) # Wait before retry on timeout
                continue
            else:
                return False, "", last_error

        except aiohttp.ClientError as e:
            last_error = f"Client error: {str(e)}"
            logging.error(f"{url}: {last_error}")
            # Assume most client errors are persistent, don't retry unless it's clearly transient
            # (We already handle timeouts above)
            return False, "", last_error # Stop after client error

        except Exception as e:
            # Catch any other unexpected errors
            last_error = f"Unexpected error: {str(e)}"
            logging.error(f"{url}: {last_error}", exc_info=True)
            return False, "", last_error # Stop on unexpected errors

    # This part should theoretically not be reached, but added for safety
    return False, "", f"Failed to fetch after {max_retries + 1} attempts. Last error: {last_error}"

async def process_contact(session: aiohttp.ClientSession, sheets_service, spreadsheet_id, 
                          access_token: str, website: str, email: str, 
                          sender_email: str, i: int, total: int, semaphore) -> Tuple[bool, float, str]:
    """Process a single contact and create a draft email"""
    start_time = time.time()
    error_message = ""
    
    async with semaphore:  # Use semaphore to limit concurrent requests
        try:
            print(f"\nProcessing draft for {email} ({i}/{total})")
            
            # Validate email early to skip invalid entries
            if not is_valid_email(email):
                error_message = f"Invalid email format, skipping: {email}"
                logging.error(error_message)
                # Mark as emailed since this is a permanent error
                try:
                    await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                except SheetsAuthError as e:
                    # Propagate sheets auth errors to be handled by batch processor
                    raise
                return False, time.time() - start_time, error_message
            
            # Check if already emailed using cached data
            if check_if_already_emailed(sheets_service, spreadsheet_id, email):
                logging.info(f"Skipping {email} - already emailed")
                return True, time.time() - start_time, "Already emailed"
                
            # Get website content (now only tries once with ~20s timeout)
            try:
                success, page_content, fetch_error = await fetch_website_with_retries(session, website)
            except Exception as e:
                # Catch potential errors during the fetch itself
                success = False
                fetch_error = f"Error during fetch: {str(e)}"
                logging.error(f"Exception calling fetch_website_with_retries for {website}: {fetch_error}")

            if not success:
                # Use the error captured from fetch_website_with_retries or the exception above
                error_message = f"Failed to fetch website {website}: {fetch_error}"
                logging.error(error_message)
                
                # Only mark as emailed if this is a permanent error
                if not is_transient_error(fetch_error):
                    try:
                        await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent website failure: {fetch_error}")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                else:
                    logging.warning(f"Not marking {email} as emailed due to transient error: {fetch_error}")
                
                return False, time.time() - start_time, error_message
            
            # Create customized email
            try:
                subject, content = create_customized_email(website, email, page_content)
            except Exception as custom_error:
                error_message = f"Failed to create customized email: {str(custom_error)}"
                logging.error(error_message)
                
                # Only mark as emailed if this is a permanent error
                if not is_transient_error(str(custom_error)):
                    try:
                        await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent customization error")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                return False, time.time() - start_time, error_message
            
            # Create draft directly with HTTP and handle retries
            success, api_error = await create_draft_with_http_async(
                session=session,
                access_token=access_token,
                to_email=email,
                subject=subject,
                content=content,
                from_email=sender_email
            )
            
            if success:
                # Only mark as emailed if the draft was successfully created
                try:
                    await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                    elapsed = time.time() - start_time
                    logging.info(f"Created draft email for {email} ({website}) in {elapsed:.2f}s")
                except Exception as e:
                    logging.error(f"Failed to mark {email} as emailed after successful draft: {str(e)}")
                return True, time.time() - start_time, ""
            else:
                error_message = f"Failed to create draft: {api_error}"
                logging.error(error_message)
                
                # Only mark as emailed for permanent API errors
                if not is_transient_error(api_error):
                    try:
                        await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent API error")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                else:
                    logging.warning(f"Not marking {email} as emailed due to transient error: {api_error}")
                    
                # Ensure we return failure status and message
                return False, time.time() - start_time, error_message
            
        except TokenExpiredError:
            # Let token errors propagate up
            raise
            
        except SheetsAuthError:
            # Let sheets auth errors propagate up
            raise
            
        except Exception as e:
            # More detailed error logging
            error_message = str(e)
            logging.error(f"Failed to process {email}: {error_message}", exc_info=True)
            
            # Only mark as emailed for permanent errors, and be more conservative here
            if not is_transient_error(error_message):
                try:
                    await update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                    logging.info(f"Marked {email} as emailed due to permanent processing error")
                except Exception as update_error:
                    logging.error(f"Failed to mark {email} as emailed: {str(update_error)}")
            else:
                logging.warning(f"Not marking {email} as emailed due to transient error: {error_message}")
                
            # Ensure failure tuple is returned even for unexpected errors
            return False, time.time() - start_time, error_message
        finally:
            # Add a short delay between processing
            await asyncio.sleep(random.uniform(1, 2))

async def create_multiple_gmail_drafts_async(
    service_account_info: Dict,
    user_email: str,
    contacts: List[Tuple[str, str]],
    from_email: str = None,
    spreadsheet_id: str = None
) -> None:
    """
    Create multiple draft emails asynchronously
    
    Args:
        service_account_info: Service account credentials
        user_email: User email to impersonate
        contacts: List of (website, email) tuples
        from_email: Sender email address
        spreadsheet_id: Google Sheets ID for tracking
    """
    # Initialize services
    sheets_service = connect_to_sheets(service_account_info)
    access_token = get_access_token(service_account_info, user_email)
    
    if not from_email:
        from_email = user_email
        
    # Filter out invalid emails and normalize websites
    filtered_contacts = []
    for website, email in contacts:
        if is_valid_email(email):
            # Normalize website URL
            if not website.startswith(('http://', 'https://')):
                website = f"https://{website}"
            filtered_contacts.append((website, email))
        else:
            logging.warning(f"Skipping invalid email: {email}")
    
    if not filtered_contacts:
        logging.warning("No valid contacts to process")
        return
        
    # Set up concurrent processing
    # Use the configurable constant for concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)
    
    # Create a single connector for all requests, respecting the concurrency limit
    conn = aiohttp.TCPConnector(limit=MAX_CONCURRENT_WORKERS, ssl=True)
    timeout = aiohttp.ClientTimeout(total=90)  # Overall timeout for the session
    
    # Create the session *once* outside the loop
    async with aiohttp.ClientSession(
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        },
        timeout=timeout,
        connector=conn
    ) as session: 
        # Process contacts in batches using the single session
        current_index = 0
        total_processed = 0
        total_success = 0
        total_failed = 0
        
        while current_index < len(filtered_contacts):
            # Removed session creation from here
            try:
                # Process contacts in smaller batches, respecting the semaphore limit
                # Note: batch_size determines how many tasks are *created* at once, 
                # but the semaphore ensures only MAX_CONCURRENT_WORKERS run simultaneously.
                batch_size = min(MAX_CONCURRENT_WORKERS * 2, len(filtered_contacts) - current_index) # Can make batch size larger
                batch_contacts = filtered_contacts[current_index:current_index + batch_size]
                
                # Create tasks for current batch
                tasks = []
                for i, (website, email) in enumerate(batch_contacts, current_index + 1):
                    task = process_contact(
                        session=session,
                        sheets_service=sheets_service,
                        spreadsheet_id=spreadsheet_id,
                        access_token=access_token,
                        website=website,
                        email=email,
                        sender_email=from_email,
                        i=i,
                        total=len(filtered_contacts),
                        semaphore=semaphore
                    )
                    tasks.append(task)
                
                # Run batch tasks concurrently using asyncio.gather
                # return_exceptions=True ensures all tasks run even if some fail
                gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results (handle potential exceptions)
                results = [] # Keep the original results list structure for later processing
                for result in gathered_results:
                    if isinstance(result, Exception):
                        # Handle exceptions returned by gather
                        logging.error(f"Task failed with exception: {result}")
                        results.append((False, 0, str(result)))
                    else:
                        # Append successful results or results with handled errors from process_contact
                        results.append(result)

                # Process results (original loop)
                for result in results:
                    if isinstance(result, tuple) and len(result) == 3:
                        success, elapsed_time, error_msg = result
                        if success:
                            total_success += 1
                        else:
                            total_failed += 1
                            if error_msg:
                                logging.error(f"Failed to process contact: {error_msg}")
                        total_processed += 1
                    else:
                        total_failed += 1
                        logging.error(f"Unexpected result format: {result}")
                        total_processed += 1
                
                # Move to next batch
                current_index += batch_size
                
                # Add a small delay between batches
                await asyncio.sleep(2)
                
            except Exception as e:
                logging.error(f"Error processing batch: {str(e)}")
                # Ensure we still advance index even if a whole batch fails unexpectedly
                current_index += min(MAX_CONCURRENT_WORKERS * 2, len(filtered_contacts) - current_index) 
                # Update totals based on estimated batch size that failed
                failed_in_batch = min(MAX_CONCURRENT_WORKERS * 2, len(filtered_contacts) - current_index + batch_size)
                total_failed += failed_in_batch
                total_processed += failed_in_batch
    
    # Connector is automatically closed when the session using it is closed
    # No need to explicitly call await conn.close()
    
    # Log final results
    logging.info(f"Completed processing {total_processed} contacts")
    logging.info(f"Successfully processed: {total_success}")
    logging.info(f"Failed to process: {total_failed}")

def create_multiple_gmail_drafts(
    service_account_info: Dict,
    user_email: str,
    contacts: List[Tuple[str, str]],
    from_email: str = None,
    spreadsheet_id: str = None
) -> None:
    """
    Wrapper function to run the async version of create_multiple_gmail_drafts
    
    Args:
        service_account_info: Service account credentials as a dictionary
        user_email: Email of the user to impersonate
        contacts: List of (website, email) tuples
        from_email: Optional sender email (defaults to impersonated user)
        spreadsheet_id: ID of the Google Sheet to update
    """
    try:
        # Create new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async function
        loop.run_until_complete(create_multiple_gmail_drafts_async(
            service_account_info=service_account_info,
            user_email=user_email,
            contacts=contacts,
            from_email=from_email,
            spreadsheet_id=spreadsheet_id
        ))
        
        # Clean up
        loop.close()
        
    except Exception as e:
        error_msg = f"Error in create_multiple_gmail_drafts: {str(e)}"
        logging.error(error_msg, exc_info=True)
        if 'streamlit' in sys.modules:
            st.error(error_msg)
        raise  # Re-raise to be handled by the caller

def check_if_already_emailed(sheets_service, spreadsheet_id, email):
    """
    Check if an email has already been marked as emailed in the spreadsheet.
    If any instance is marked as emailed, update all instances to be marked as emailed.
    
    Args:
        sheets_service: Google Sheets service object
        spreadsheet_id: ID of the spreadsheet
        email: Email address to check
        
    Returns:
        bool: True if already emailed, False otherwise
    """
    try:
        # Use cache instead of direct API call
        leads_df = get_sheet_data_cached(sheets_service, spreadsheet_id, 'leads')
        
        # Find matching email
        if leads_df is not None and not leads_df.empty and 'Email' in leads_df.columns:
            matching_rows = leads_df[leads_df['Email'] == email]
            
            if not matching_rows.empty:
                # Check if Emailed column exists and has a value
                if 'Emailed?' in matching_rows.columns:
                    # Check if any instance of this email has been marked as emailed
                    already_emailed = any(
                        emailed_value and str(emailed_value).lower() in ('yes', 'true', '1')
                        for emailed_value in matching_rows['Emailed?']
                    )
                    
                    if already_emailed:
                        # Update all matching rows to be marked as emailed
                        leads_df.loc[leads_df['Email'] == email, 'Emailed?'] = 'True'
                        
                        # Convert back to list format for sheets API
                        values = [leads_df.columns.tolist()] + leads_df.values.tolist()
                        
                        # Write back all data
                        body = {
                            'values': values
                        }
                        sheets_service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range='leads!A1',
                            valueInputOption='RAW',
                            body=body
                        ).execute()
                        
                        # Update the cache with new data
                        try:
                            update_cache_after_write(spreadsheet_id, 'leads')
                        except Exception as cache_error:
                            logging.warning(f"Cache update failed, but sheet was updated: {str(cache_error)}")
                        
                        logging.info(f"Updated all instances of {email} to be marked as emailed")
                        return True
        
        return False
        
    except Exception as e:
        logging.error(f"Error checking if {email} was already emailed: {str(e)}")
        return False  # Assume not emailed in case of error

async def update_lead_emailed_status(service, spreadsheet_id: str, email: str) -> None:
    """
    Update the Emailed? column to True for all rows with matching email (async version)
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: ID of the spreadsheet
        email: Email address to mark as emailed
    """
    try:
        # Get existing data using cached version
        leads_df = get_sheet_data_cached(service, spreadsheet_id, 'leads')
        
        if leads_df is None or leads_df.empty:
            logging.warning("No data found in leads sheet")
            return
            
        # Check if Emailed? column exists, create it if not
        if 'Emailed?' not in leads_df.columns:
            leads_df['Emailed?'] = ''
            
        # Update matching rows
        mask = leads_df['Email'] == email
        if not mask.any():
            logging.warning(f"No matching rows found for email {email}")
            return
            
        # Mark matching rows as emailed
        leads_df.loc[mask, 'Emailed?'] = 'True'
        
        # Convert back to list format for sheets API
        values = [leads_df.columns.tolist()] + leads_df.values.tolist()
        
        # Write back all data
        body = {
            'values': values
        }
        
        # First update the sheet
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='leads!A1',
            valueInputOption='RAW',
            body=body
        ).execute()
        
        # Then update the cache
        try:
            update_cache_after_write(spreadsheet_id, 'leads')
        except Exception as cache_error:
            logging.warning(f"Cache update failed, but sheet was updated: {str(cache_error)}")
        
        logging.info(f"Updated {mask.sum()} rows for email {email}")
        
    except Exception as e:
        logging.error(f"Error updating emailed status for {email}: {str(e)}")
        raise SheetsAuthError(f"Failed to update emailed status: {str(e)}") 