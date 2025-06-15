import base64
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
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---
# Maximum number of concurrent tasks (website fetching, email creation)
MAX_CONCURRENT_WORKERS = 3  # Reduced from 10 to avoid network congestion
# Session recreation interval to prevent stale connections
SESSION_REFRESH_INTERVAL = 25  # Refresh session every 25 contacts
# ---

# Ensure required packages are available
try:
    import jwt
except ImportError:
    logging.error("PyJWT package is required. Please run 'pip install PyJWT[crypto]' and restart.")
    raise ImportError("PyJWT is required")

try:
    import aiohttp
except ImportError:
    logging.error("aiohttp package is required. Please run 'pip install aiohttp' and restart.")
    raise ImportError("aiohttp is required")

from app.local_settings import (
    OPENAI_API_KEY_GPT4,
    firestore_creds,
    GMAIL_USER_EMAIL
)

from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.utils.sheet_cache import get_sheet_data_cached, update_cache_after_write

from app.core.email_utils import (
    normalize_url,
    analyze_website_content,
    select_email_template,
    customize_template,
    refine_template_customization,
    create_customized_email
)

from app.core.create_zoho_drafts import (
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

async def refresh_access_token(service_account_info: Dict, user_email: str) -> str:
    """
    Refresh the Gmail API access token
    
    Args:
        service_account_info: Service account credentials as a dictionary
        user_email: Email to impersonate
        
    Returns:
        str: New access token
    """
    try:
        logging.info("Refreshing Gmail API access token...")
        new_token = get_access_token(service_account_info, user_email)
        logging.info("Successfully refreshed Gmail API access token")
        return new_token
    except Exception as e:
        logging.error(f"Failed to refresh access token: {str(e)}")
        raise TokenExpiredError(f"Failed to refresh access token: {str(e)}")

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
    
    # Permanent errors (should not retry) - check these first
    permanent_patterns = [
        'invalid email',
        'malformed',
        'not found',
        'forbidden',
        'unauthorized',
        'permission denied',
        'invalid request',
        'bad request',
        'nodename nor servname provided',  # DNS resolution failure
        'name or service not known',       # Another DNS failure variant
        'no address associated with hostname',  # DNS failure
        'name resolution failed',          # DNS failure
        'host not found',                  # DNS failure
        'domain not found',                # DNS failure
        'cannot resolve hostname',         # DNS failure
        'getaddrinfo failed',             # DNS failure variant
        'cannot connect to host',         # Connection failure - this should be permanent
        'connection refused',             # Often permanent when site is down
        'ssl',                           # SSL errors are usually permanent config issues
        'certificate',                   # Certificate errors are permanent
        'tlsv1_alert',                   # SSL/TLS errors are permanent
        'ssl handshake',                 # SSL handshake failures are permanent
        '[none]',                        # The [None] error indicates permanent failure
        'internal error',                # SSL internal errors are permanent
    ]
    
    # Check if any permanent pattern matches first
    for pattern in permanent_patterns:
        if pattern in error_lower:
            return False
    
    # Network-related transient errors (much more limited now)
    transient_patterns = [
        'timeout',                        # Only timeouts should be considered transient
        'network unreachable',           # Network routing issues might be temporary
        'temporary failure',
        'service unavailable',
        'bad gateway',
        'gateway timeout',
        'too many requests',
        'rate limit',
        'quota exceeded',
        'server error',
        'internal server error',
        'unexpected result format',
        'token may have expired',
        'authentication failed',
    ]
    
    # Check if any transient pattern matches
    for pattern in transient_patterns:
        if pattern in error_lower:
            return True
    
    # If uncertain, err on the side of being PERMANENT (mark as emailed) to avoid endless retries
    # This is the key change - when in doubt, mark as done rather than keep retrying
    return False

async def create_draft_with_http_async(session: aiohttp.ClientSession, access_token: str, 
                                  to_email: str, subject: str, content: str, from_email: str,
                                  service_account_info: Dict = None, user_email: str = None
                                  ) -> Tuple[bool, str, str]:
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
        service_account_info: Service account credentials for token refresh
        user_email: User email for token refresh
        
    Returns:
        Tuple[bool, str, str]: (Success status, Error message if any, New access token if refreshed)
    """
    error_msg = ""
    max_api_retries = 2 # Increase retries to allow for token refresh
    current_token = access_token
    
    for attempt in range(max_api_retries + 1):
        try:
            # Validate email first
            if not is_valid_email(to_email):
                return False, f"Invalid email format: {to_email}", current_token
            
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
                'Authorization': f'Bearer {current_token}',
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
                    return True, "", current_token
                else:
                    response_text = await response.text()
                    error_msg = f"Error creating draft: {response.status} - {response_text}"
                    logging.error(error_msg)
                    
                    # Check for auth errors (401) or timeout-related errors
                    if response.status == 401 or "token" in error_msg.lower():
                        if service_account_info and user_email and attempt < max_api_retries:
                            try:
                                logging.info("Attempting to refresh access token due to auth error")
                                current_token = await refresh_access_token(service_account_info, user_email)
                                await asyncio.sleep(2)  # Short delay before retry
                                continue  # Retry with new token
                            except Exception as refresh_error:
                                error_msg = f"Token refresh failed: {str(refresh_error)}"
                                logging.error(error_msg)
                                return False, error_msg, current_token
                        else:
                            return False, f"TokenExpiredError: Gmail API token may have expired ({error_msg})", current_token
                    
                    # Treat other non-success as failures for this attempt
                    # Only retry on 5xx server errors
                    if response.status >= 500 and attempt < max_api_retries:
                        error_msg = f"Received {response.status} from Gmail API, retrying..."
                        logging.warning(error_msg)
                        await asyncio.sleep(3 * (attempt + 1)) # Short delay before API retry
                        continue # Go to next attempt in the loop
                    else:
                        # Permanent client error or final attempt failed
                        return False, error_msg, current_token
                
        except TokenExpiredError as e: # Should not be raised anymore, but keep catch just in case
            logging.error(f"TokenExpiredError caught unexpectedly: {e}")
            return False, str(e), current_token
        
        except asyncio.TimeoutError as e:
            error_msg = f"Timeout error connecting to Gmail API: {str(e)}"
            logging.error(error_msg)
            
            # Try to refresh token on timeout if we have credentials and retries left
            if service_account_info and user_email and attempt < max_api_retries:
                try:
                    logging.info("Attempting to refresh access token due to timeout")
                    current_token = await refresh_access_token(service_account_info, user_email)
                    await asyncio.sleep(3 * (attempt + 1))  # Longer delay after timeout
                    continue  # Retry with new token
                except Exception as refresh_error:
                    error_msg = f"Token refresh after timeout failed: {str(refresh_error)}"
                    logging.error(error_msg)
                    return False, error_msg, current_token
            else:
                # Retry once more on timeout without refresh if no credentials
                if attempt < max_api_retries:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                else:
                    return False, error_msg, current_token # Final attempt timed out
            
        except Exception as e:
            error_msg = f"Error in create_draft_with_http_async: {str(e)}"
            logging.error(error_msg, exc_info=True) # Log full traceback
            return False, error_msg, current_token

    # If loop finishes without returning (shouldn't happen with retry logic)
    return False, f"Failed after {max_api_retries + 1} attempts: {error_msg}", current_token

class ServiceAuthError(Exception):
    """Base class for service authentication errors"""
    pass

class TokenExpiredError(ServiceAuthError):
    """Raised when the Gmail API token has expired"""
    pass

class SheetsAuthError(ServiceAuthError):
    """Raised when the Sheets API authentication fails"""
    pass

async def is_session_healthy(session: aiohttp.ClientSession) -> bool:
    """
    Check if the aiohttp session is still healthy
    
    Args:
        session: The aiohttp ClientSession to check
        
    Returns:
        bool: True if session is healthy, False otherwise
    """
    try:
        # Simple health check - try to make a minimal request
        async with session.get('https://httpbin.org/status/200', timeout=aiohttp.ClientTimeout(total=5)) as response:
            return response.status == 200
    except Exception:
        return False

async def create_fresh_session() -> aiohttp.ClientSession:
    """
    Create a fresh aiohttp session with proper configuration
    
    Returns:
        aiohttp.ClientSession: A new configured session
    """
    # Create a single connector for all requests, respecting the concurrency limit
    conn = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT_WORKERS, 
        limit_per_host=2,  # Max 2 connections per host to avoid overwhelming servers
        ssl=True,
        keepalive_timeout=30,  # Keep connections alive for 30s
        enable_cleanup_closed=True
    )
    
    # Much more reasonable timeout for normal websites
    timeout = aiohttp.ClientTimeout(
        total=30,      # Overall request timeout - reduced from 90s
        connect=10,    # Connection establishment timeout
        sock_read=15   # Socket read timeout
    )
    
    return aiohttp.ClientSession(
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        },
        timeout=timeout,
        connector=conn
    )

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
                # Accept all 2xx status codes as success (200, 201, 202, etc.)
                if 200 <= response.status < 300:
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
                          access_token: str, website: str, email: str, notes: str, 
                          sender_email: str, i: int, total: int, semaphore,
                          service_account_info: Dict, user_email: str) -> Tuple[bool, float, str, str]:
    """Process a single contact and create a draft email"""
    start_time = time.time()
    error_message = ""
    current_token = access_token
    
    async with semaphore:  # Use semaphore to limit concurrent requests
        try:
            print(f"\nProcessing draft for {email} ({i}/{total})")
            
            # Validate email early to skip invalid entries
            if not is_valid_email(email):
                error_message = f"Invalid email format, skipping: {email}"
                logging.error(error_message)
                # Mark as emailed since this is a permanent error
                try:
                    update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                except SheetsAuthError as e:
                    # Propagate sheets auth errors to be handled by batch processor
                    raise
                return False, time.time() - start_time, error_message, current_token
            
            # Check if already emailed using cached data
            if check_if_already_emailed(sheets_service, spreadsheet_id, email):
                logging.info(f"Skipping {email} - already emailed")
                return True, time.time() - start_time, "Already emailed", current_token
                
            # Get website content with retries for transient failures
            try:
                success, page_content, fetch_error = await fetch_website_with_retries(session, website, max_retries=1)
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
                        update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent website failure: {fetch_error}")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                else:
                    logging.warning(f"Not marking {email} as emailed due to transient error: {fetch_error}")
                
                return False, time.time() - start_time, error_message, current_token
            
            # Create customized email
            try:
                subject, content = create_customized_email(website, email, page_content, notes)
            except Exception as custom_error:
                error_message = f"Failed to create customized email: {str(custom_error)}"
                logging.error(error_message)
                
                # Only mark as emailed if this is a permanent error
                if not is_transient_error(str(custom_error)):
                    try:
                        update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent customization error")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                return False, time.time() - start_time, error_message, current_token
            
            # Create draft directly with HTTP and handle retries
            success, api_error, new_token = await create_draft_with_http_async(
                session=session,
                access_token=current_token,
                to_email=email,
                subject=subject,
                content=content,
                from_email=sender_email,
                service_account_info=service_account_info,
                user_email=user_email
            )
            
            # Update current token if it was refreshed
            if new_token != current_token:
                current_token = new_token
                logging.info(f"Updated access token for {email}")
            
            if success:
                # Only mark as emailed if the draft was successfully created
                try:
                    update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                    elapsed = time.time() - start_time
                    logging.info(f"Created draft email for {email} ({website}) in {elapsed:.2f}s")
                except Exception as e:
                    logging.error(f"Failed to mark {email} as emailed after successful draft: {str(e)}")
                return True, time.time() - start_time, "", current_token
            else:
                error_message = f"Failed to create draft: {api_error}"
                logging.error(error_message)
                
                # Only mark as emailed for permanent API errors
                if not is_transient_error(api_error):
                    try:
                        update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                        logging.info(f"Marked {email} as emailed due to permanent API error")
                    except Exception as e:
                        logging.error(f"Failed to mark {email} as emailed: {str(e)}")
                else:
                    logging.warning(f"Not marking {email} as emailed due to transient error: {api_error}")
                    
                # Ensure we return failure status and message
                return False, time.time() - start_time, error_message, current_token
            
        except TokenExpiredError:
            # Let token errors propagate up
            raise
            
        except SheetsAuthError:
            # Let sheets auth errors propagate up
            raise
        
        # Handle Streamlit-specific exceptions
        except Exception as e:
            # Check if this is a Streamlit StopException
            if 'streamlit' in str(type(e)).lower() and 'stop' in str(type(e)).lower():
                logging.info(f"Streamlit session stopped while processing {email}, gracefully exiting")
                # Return a special indicator that this was a session stop, not a real error
                return False, time.time() - start_time, "SESSION_STOPPED", current_token
            
            # More detailed error logging for other exceptions
            error_message = str(e)
            logging.error(f"Failed to process {email}: {error_message}", exc_info=True)
            
            # Only mark as emailed for permanent errors, and be more conservative here
            if not is_transient_error(error_message):
                try:
                    update_lead_emailed_status(sheets_service, spreadsheet_id, email)
                    logging.info(f"Marked {email} as emailed due to permanent processing error")
                except Exception as update_error:
                    logging.error(f"Failed to mark {email} as emailed: {str(update_error)}")
            else:
                logging.warning(f"Not marking {email} as emailed due to transient error: {error_message}")
                
            # Ensure failure tuple is returned even for unexpected errors
            return False, time.time() - start_time, error_message, current_token
        finally:
            # Add a short delay between processing
            await asyncio.sleep(random.uniform(1, 2))

async def create_multiple_gmail_drafts_async(
    service_account_info: Dict,
    user_email: str,
    contacts: List[Tuple[str, str, str]],
    from_email: str = None,
    spreadsheet_id: str = None
) -> None:
    """
    Create multiple draft emails asynchronously
    
    Args:
        service_account_info: Service account credentials
        user_email: User email to impersonate
        contacts: List of (website, email, notes) tuples
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
    for website, email, notes in contacts:
        if is_valid_email(email):
            # Normalize website URL
            if not website.startswith(('http://', 'https://')):
                website = f"https://{website}"
            filtered_contacts.append((website, email, notes))
        else:
            logging.warning(f"Skipping invalid email: {email}")
    
    if not filtered_contacts:
        logging.warning("No valid contacts to process")
        return
        
    # Set up concurrent processing
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)
    
    # Create initial session
    session = await create_fresh_session()
    
    try:
        # Process contacts in batches using the session
        current_index = 0
        total_processed = 0
        total_success = 0
        total_failed = 0
        
        # Refresh token, sheets service, and session every REFRESH_INTERVAL contacts
        REFRESH_INTERVAL = 10  # Reduced from 20 to be more aggressive
        contacts_since_refresh = 0
        
        while current_index < len(filtered_contacts):
            try:
                # Refresh connections every REFRESH_INTERVAL contacts
                if contacts_since_refresh >= REFRESH_INTERVAL:
                    logging.info("Refreshing connections after processing batch...")
                    try:
                        # Check session health and recreate if needed
                        if not await is_session_healthy(session):
                            logging.info("Session unhealthy, recreating...")
                            await session.close()
                            session = await create_fresh_session()
                        
                        # Refresh Gmail token
                        access_token = await refresh_access_token(service_account_info, user_email)
                        # Refresh Sheets service
                        sheets_service = await refresh_sheets_service(spreadsheet_id)
                        contacts_since_refresh = 0
                        logging.info("Successfully refreshed connections")
                        await asyncio.sleep(2)  # Brief pause after refresh
                    except Exception as refresh_error:
                        logging.error(f"Failed to refresh connections: {refresh_error}")
                        # Try to recreate session even if other refreshes failed
                        try:
                            await session.close()
                            session = await create_fresh_session()
                            logging.info("Recreated session after refresh failure")
                        except Exception as session_error:
                            logging.error(f"Failed to recreate session: {session_error}")
                
                batch_size = min(MAX_CONCURRENT_WORKERS * 2, len(filtered_contacts) - current_index)
                batch_contacts = filtered_contacts[current_index:current_index + batch_size]
                
                # Create tasks for current batch
                tasks = []
                for i, (website, email, notes) in enumerate(batch_contacts, current_index + 1):
                    task = process_contact(
                        session=session,
                        sheets_service=sheets_service,
                        spreadsheet_id=spreadsheet_id,
                        access_token=access_token,
                        website=website,
                        email=email,
                        notes=notes,
                        sender_email=from_email,
                        i=i,
                        total=len(filtered_contacts),
                        semaphore=semaphore,
                        service_account_info=service_account_info,
                        user_email=user_email
                    )
                    tasks.append(task)
                
                # Run batch tasks concurrently with timeout
                try:
                    # Add a timeout to prevent hanging
                    gathered_results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=300  # 5 minutes max per batch
                    )
                except asyncio.TimeoutError:
                    logging.error(f"Batch timed out after 5 minutes, moving to next batch")
                    # Mark all contacts in this batch as failed
                    total_failed += len(batch_contacts)
                    total_processed += len(batch_contacts)
                    current_index += batch_size
                    contacts_since_refresh += batch_size
                    continue
                
                # Process results (handle potential exceptions)
                results = []
                for result in gathered_results:
                    if isinstance(result, Exception):
                        # Check if this is a Streamlit StopException
                        if 'streamlit' in str(type(result)).lower() and 'stop' in str(type(result)).lower():
                            logging.info("Streamlit session stopped, gracefully terminating batch processing")
                            # Stop processing immediately when Streamlit wants to stop
                            return
                        else:
                            logging.error(f"Task failed with exception: {result}")
                            results.append((False, 0, str(result), access_token))
                    else:
                        results.append(result)

                for result in results:
                    # More robust result handling
                    if isinstance(result, tuple):
                        if len(result) == 4:
                            success, elapsed_time, error_msg, token = result
                            # Update access token if it was refreshed during processing
                            if token and token != access_token:
                                access_token = token
                                
                            # Handle session stopped case
                            if error_msg == "SESSION_STOPPED":
                                logging.info("Session stopped detected, terminating batch processing")
                                return
                                
                        elif len(result) == 3:
                            # Handle legacy 3-tuple results
                            success, elapsed_time, error_msg = result
                            
                            # Handle session stopped case for legacy results
                            if error_msg == "SESSION_STOPPED":
                                logging.info("Session stopped detected, terminating batch processing")
                                return
                        else:
                            # Unexpected tuple length
                            logging.error(f"Unexpected result tuple length: {len(result)} - {result}")
                            success = False
                            error_msg = f"Malformed result tuple: {result}"
                        
                        if success:
                            total_success += 1
                        else:
                            total_failed += 1
                            if error_msg and error_msg != "SESSION_STOPPED":
                                logging.error(f"Failed to process contact: {error_msg}")
                        total_processed += 1
                    else:
                        total_failed += 1
                        logging.error(f"Unexpected result format: {result} (type: {type(result)})")
                        total_processed += 1
                
                current_index += batch_size
                contacts_since_refresh += batch_size
                
                # Progress update
                logging.info(f"Batch complete: {total_processed}/{len(filtered_contacts)} processed, {total_success} successful, {total_failed} failed")
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logging.error(f"Error processing batch: {str(e)}", exc_info=True)
                # Calculate how many contacts were in the failed batch
                failed_batch_size = min(MAX_CONCURRENT_WORKERS * 2, len(filtered_contacts) - current_index)
                current_index += failed_batch_size
                total_failed += failed_batch_size
                total_processed += failed_batch_size
                contacts_since_refresh += failed_batch_size
    
    finally:
        # Always close the session when done
        if session and not session.closed:
            await session.close()
            logging.info("Closed aiohttp session")
    
    logging.info(f"Completed processing {total_processed} contacts")
    logging.info(f"Successfully processed: {total_success}")
    logging.info(f"Failed to process: {total_failed}")

def create_multiple_gmail_drafts(
    service_account_info: Dict,
    user_email: str,
    contacts: List[Tuple[str, str, str]],
    from_email: str = None,
    spreadsheet_id: str = None
) -> None:
    """
    Wrapper function to run the async version of create_multiple_gmail_drafts
    
    Args:
        service_account_info: Service account credentials as a dictionary
        user_email: Email of the user to impersonate
        contacts: List of (website, email, notes) tuples
        from_email: Optional sender email (defaults to impersonated user)
        spreadsheet_id: ID of the Google Sheet to update
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(create_multiple_gmail_drafts_async(
            service_account_info=service_account_info,
            user_email=user_email,
            contacts=contacts,
            from_email=from_email,
            spreadsheet_id=spreadsheet_id
        ))
        loop.close()
        
    except Exception as e:
        error_msg = f"Error in create_multiple_gmail_drafts: {str(e)}"
        logging.error(error_msg, exc_info=True)
        raise  # Re-raise to be handled by the caller 