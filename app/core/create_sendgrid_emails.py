import streamlit as st
import requests
from typing import List, Dict, Tuple, Optional
import logging
import html2text
from app.utils.sendgrid_utils import send_email_via_sendgrid
from app.utils.gcs import connect_to_sheets


from app.core.create_zoho_drafts import (
    create_customized_email,
    update_lead_emailed_status,
    check_if_already_emailed
)

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')

def html_to_plain_text(html_content):
    """Convert HTML content to plain text."""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0  # Don't wrap text
    return h.handle(html_content)

def generate_email_for_contact(website: str, email: str) -> Optional[Dict]:
    """
    Generate an email for a single contact without sending it
    
    Args:
        website: Contact website
        email: Contact email
        
    Returns:
        Dict with email details or None if generation failed
    """
    try:
        # Create a browser session to get website content
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        
        # Get website content
        response = session.get(website, timeout=30)
        response.raise_for_status()
        page_content = response.text
        
        # Create customized email
        subject, html_content = create_customized_email(website, email, page_content)
        
        # Convert HTML to plain text for the text version
        text_content = html_to_plain_text(html_content)
        
        return {
            "website": website,
            "email": email,
            "subject": subject,
            "html_content": html_content,
            "text_content": text_content
        }
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch website {website}: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Failed to generate email for {email}: {str(e)}")
        return None

def generate_emails_for_contacts(contacts: List[Tuple[str, str]], service=None, spreadsheet_id=None) -> List[Dict]:
    """
    Generate emails for a list of contacts without sending them
    
    Args:
        contacts: List of (website, email) tuples
        service: Google Sheets service (optional)
        spreadsheet_id: Google Sheet ID (optional)
        
    Returns:
        List of generated email dictionaries
    """
    if spreadsheet_id is None and 'spreadsheet_id' in st.session_state:
        spreadsheet_id = st.session_state.spreadsheet_id
    
    if service is None and spreadsheet_id is not None:
        service = connect_to_sheets(spreadsheet_id)
    
    generated_emails = []
    
    for website, email in contacts:
        try:
            # Check if already emailed
            if service and spreadsheet_id and check_if_already_emailed(service, spreadsheet_id, email):
                logging.info(f"Skipping {email} - already emailed")
                continue
            
            # Generate the email
            email_data = generate_email_for_contact(website, email)
            if email_data:
                generated_emails.append(email_data)
                logging.info(f"Generated email for {email}")
            
        except Exception as e:
            logging.error(f"Failed to process {email}: {str(e)}")
            continue
    
    return generated_emails

def send_single_email(
    email_data: Dict,
    from_email: str,
    from_name: str = None,
    service=None,
    spreadsheet_id=None,
    include_plain_text: bool = False
) -> bool:
    """
    Send a single email via SendGrid and mark as sent if successful
    
    Args:
        email_data: Dictionary with email details
        from_email: Sender email
        from_name: Sender name (optional)
        service: Google Sheets service (optional)
        spreadsheet_id: Google Sheet ID (optional)
        include_plain_text: Whether to include plain text version (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    if spreadsheet_id is None and 'spreadsheet_id' in st.session_state:
        spreadsheet_id = st.session_state.spreadsheet_id
    
    if service is None and spreadsheet_id is not None:
        service = connect_to_sheets(spreadsheet_id)
    
    sender = (from_email, from_name) if from_name else from_email
    
    # Hardcoded recipient email for all messages
    hardcoded_recipient = "matt.toronto97@gmail.com"
    
    try:
        # Send email via SendGrid
        success = send_email_via_sendgrid(
            subject=email_data["subject"],
            sender=sender,
            recipients=hardcoded_recipient,  # Use hardcoded email
            text_body=email_data["text_content"] if include_plain_text else None,
            html_body=email_data["html_content"]
        )
        
        if success and service and spreadsheet_id:
            # Update leads sheet to mark as emailed
            update_lead_emailed_status(service, spreadsheet_id, email_data["email"])
            logging.info(f"Sent email (intended for {email_data['email']}) to {hardcoded_recipient}")
        
        return success
    
    except Exception as e:
        logging.error(f"Failed to send email to {hardcoded_recipient} (intended for {email_data['email']}): {str(e)}")
        return False 