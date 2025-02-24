import streamlit as st
import requests
from typing import List, Dict, Tuple
import logging
from datetime import datetime, timedelta
import re
from pathlib import Path
from app.local_settings import (
    ZOHO_MAIL_CLIENT_ID,
    ZOHO_MAIL_CLIENT_SECRET,
    ZOHO_MAIL_REFRESH_TOKEN,
    OPENAI_API_KEY_GPT4,
    firestore_creds
)

from app.utils.gcs import connect_to_sheets, get_sheet_data

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



def normalize_url(url: str) -> str:
    """
    Normalize URL by adding https:// if no scheme is present
    
    Args:
        url: URL to normalize
        
    Returns:
        Normalized URL with scheme
    """
    if not url.startswith(('http://', 'https://')):
        return f'https://{url}'
    return url

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

def analyze_website_content(url: str, page_content: str) -> WebsiteAnalysis:
    """
    Analyze website content using LLM to extract relevant information
    
    Args:
        url: Website URL
        page_content: HTML content of the page
        
    Returns:
        WebsiteAnalysis object with extracted information
    """
    # Extract business name from URL for fallback
    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        domain_parts = parsed_url.netloc.split('.')
        if domain_parts[0] == 'www':
            domain_parts = domain_parts[1:]
        business_name = ' '.join(word.capitalize() for word in domain_parts[0].split('-'))
    except Exception as e:
        logging.error(f"Error extracting business name from URL: {str(e)}")
        business_name = url.split("//")[-1].split("/")[0]

    # Truncate page content if too long
    max_content_length = 8000  # Adjust based on token limits
    if len(page_content) > max_content_length:
        page_content = page_content[:max_content_length] + "..."

    messages = [
        {
            "role": "system", 
            "content": f"""You are an AI trained to analyze business websites for lead generation for a platform called Zakaya.
Extract key information about the business that would be relevant for personalizing an email about a community platform. Focus on aspects related to community, events, and engagement.

Return a JSON object formatted as follows:
{website_analysis_adapter.get_format_instructions()}
"""
        },
        {"role": "user", "content": f"For context, here is some context about Zakaya:\n{ZAKAYA_CONTEXT}"},
        {
            "role": "user", 
            "content": f"Please analyze this website content:\n\nURL: {url}\n\nContent:\n{page_content}"
        }
    ]
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY_GPT4}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 1000
            },
            timeout=30
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Parse the JSON content directly
        return website_analysis_adapter.parse(content)
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling OpenAI API: {str(e)}")
    except Exception as e:
        logging.error(f"Error analyzing website: {str(e)}")
    
    # Return default analysis
    return WebsiteAnalysis(
        summary="Could not analyze website",
        business_type="unknown",
        business_name=business_name,
        key_features=[],
        community_aspects=[],
        contact_person=None
    )

def select_email_template(analysis: WebsiteAnalysis) -> TemplateSelection:
    """
    Select the best email template based on website analysis
    
    Args:
        analysis: WebsiteAnalysis object
        
    Returns:
        TemplateSelection object with selected template and reason
    """
    messages = [
        {"role": "system", "content": f"""You are an AI trained to select the best email template for a business.
Choose from these templates: {", ".join(EMAIL_TEMPLATES.keys())}.
Base your decision on the business analysis provided.

Return a JSON object formatted as follows:
{template_selection_adapter.get_format_instructions()}
"""},
        {
            "role": "user", 
            "content": f"Please select a template based on this analysis:\n{analysis.model_dump_json()}"
        }
    ]
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY_GPT4}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",
                "messages": messages,
                "temperature": 0.1
            }
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Parse the JSON content directly
        return template_selection_adapter.parse(content)
    except Exception as e:
        logging.error(f"Error selecting template: {str(e)}")
        # Return default template
        return TemplateSelection(
            template_key="coworking",
            reason="Error in template selection, using default",
            customization_needed=True
        )

def customize_template(template_key: str, analysis: WebsiteAnalysis) -> TemplateCustomization:
    """
    Customize the selected template based on website analysis
    
    Args:
        template_key: Key of the selected template
        analysis: WebsiteAnalysis object
        
    Returns:
        TemplateCustomization object with customization details
    """
    messages = [
        {"role": "system", "content": WRITE_EMAIL_PROMPT.render(template_key=template_key, template_extra_context=EMAIL_TEMPLATES[template_key]["extra_context"], format_instruction=template_customization_adapter.get_format_instructions())},
        {"role": "user", "content": f"For context, here is some context about Zakaya:\n{ZAKAYA_CONTEXT}"},
        {"role": "user", "content": f"Please customize the template based on this analysis:\n{analysis.model_dump_json()}"}
    ]
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY_GPT4}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",
                "messages": messages,
                "temperature": 0.3
            }
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Parse the JSON content directly
        return template_customization_adapter.parse(content)
    except Exception as e:
        logging.error(f"Error customizing template: {str(e)}")
        # Return default customization
        return TemplateCustomization(
            subject_line=EMAIL_TEMPLATES[template_key]["subject"].format(business_name=analysis.business_name),
            custom_intro="I came across your website and was impressed by your business.",
            key_points=["<span class='highlight'>Chat rooms and forums</span> for your community to connect",
                       "<span class='highlight'>Event calendar</span> for coordinating activities",
                       "<span class='highlight'>Member profiles</span> to help people get to know each other"],
            custom_closing="Would love to show you how this could work for your community!",
            specific_references=[]
        )

def refine_template_customization(customization: TemplateCustomization, analysis: WebsiteAnalysis) -> TemplateCustomization:
    """
    Refine and clean up the template customization to avoid repetition and improve flow
    
    Args:
        customization: Initial TemplateCustomization object
        analysis: WebsiteAnalysis object for context
        
    Returns:
        Refined TemplateCustomization object
    """
    messages = [
        {
            "role": "system",
            "content": REFINE_EMAIL_PROMPT.render(format_instruction=template_customization_adapter.get_format_instructions())
        },
        {
            "role": "user",
            "content": f"""
Here is the business we are reaching out to:
BUSINESS CONTEXT:
{analysis.model_dump_json()}
""".strip()
        },
        {
            "role": "user",
            "content": f"""
Here is the current draft email content to refine:
CURRENT EMAIL SECTIONS:
{customization.model_dump_json()}
""".strip()
        },
    ]
    
    try:
        response = _llm(messages, temp=0.3)
        # Parse the JSON content directly
        return template_customization_adapter.parse(response)
    except Exception as e:
        logging.error(f"Error refining template customization: {str(e)}")
        return customization  # Return original if refinement fails

def create_customized_email(website: str, email: str, page_content: str) -> Tuple[str, str]:
    """
    Create a customized email for a business based on their website content
    
    Args:
        website: Business website URL
        email: Recipient email address
        page_content: HTML content of the website
        
    Returns:
        Tuple of (subject, content) for the email
    """
    # Analyze website
    analysis = analyze_website_content(website, page_content)
    logging.info(f"Website analysis complete for {website}")
    
    # Select template
    template_selection = select_email_template(analysis)
    logging.info(f"Selected template: {template_selection.template_key}")
    
    # Get template
    template = EMAIL_TEMPLATES[template_selection.template_key]
    
    # Customize template
    customization = customize_template(template_selection.template_key, analysis)
    logging.info(f"Template customization complete for {website}")
    
    # Refine the customization
    refined_customization = refine_template_customization(customization, analysis)
    logging.info(f"Template refinement complete for {website}")
    
    # Format key points as HTML list items
    key_points_html = "\n".join([
        f"        <li>{point}</li>" for point in refined_customization.key_points
    ])
    
    # Create email content using the helper function
    content = get_email_content(
        safe_name=refined_customization.safe_name,
        template_key=template_selection.template_key,
        custom_intro=refined_customization.custom_intro,
        key_points=key_points_html,
        custom_closing=refined_customization.custom_closing,
        lead_url=website
    )
    
    # Create subject
    subject = template["subject"].format(business_name=analysis.business_name)
    if refined_customization.subject_line:  # Use custom subject if provided
        subject = refined_customization.subject_line
    
    return subject, content

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

class ZohoMailAPI:
    """Class to handle Zoho Mail API operations"""
    
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None
        self.token_expiry = None
        self.account_id = None
        self.spreadsheet_id = st.session_state.spreadsheet_id
        self.service = connect_to_sheets(self.spreadsheet_id)
        
    def update_refresh_token_in_settings(self, new_refresh_token: str):
        """Update the refresh token in local_settings.py"""
        settings_path = Path(__file__).parent / 'local_settings.py'
        
        with open(settings_path, 'r') as file:
            content = file.read()
        
        # Update the refresh token
        pattern = r'(ZOHO_MAIL_REFRESH_TOKEN\s*=\s*)["\'].*?["\']'
        new_content = re.sub(pattern, f'\\1"{new_refresh_token}"', content)
        
        with open(settings_path, 'w') as file:
            file.write(new_content)
        
        self.refresh_token = new_refresh_token
        logging.info("Updated refresh token in local_settings.py")

    def get_new_refresh_token(self) -> str:
        """Get a new refresh token using the current one"""
        url = "https://accounts.zoho.com/oauth/v2/token/refresh"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            if 'refresh_token' in token_data:
                new_refresh_token = token_data['refresh_token']
                self.update_refresh_token_in_settings(new_refresh_token)
                return new_refresh_token
            
            return self.refresh_token
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get new refresh token: {str(e)}")
            raise

    def get_access_token(self) -> str:
        """Get a new access token using the refresh token"""
        if (self.access_token and self.token_expiry 
            and datetime.now() < self.token_expiry):
            return self.access_token
            
        url = "https://accounts.zoho.com/oauth/v2/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        
        try:
            response = requests.post(url, data=data)
            if response.status_code == 400:
                # Try to get a new refresh token
                self.refresh_token = self.get_new_refresh_token()
                data["refresh_token"] = self.refresh_token
                response = requests.post(url, data=data)
            
            response.raise_for_status()
            token_data = response.json()
            
            self.access_token = token_data["access_token"]
            # Token typically expires in 1 hour
            self.token_expiry = datetime.now() + timedelta(seconds=3600)
            
            return self.access_token
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get access token: {str(e)}")
            raise

    def get_account_id(self) -> str:
        """Get the Zoho Mail account ID"""
        if self.account_id:
            return self.account_id

        url = "https://mail.zoho.com/api/accounts"
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.get_access_token()}"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            accounts = response.json()
            
            if not accounts.get("data"):
                raise Exception("No accounts found")
                
            # Use the first account
            self.account_id = str(accounts["data"][0]["accountId"])
            return self.account_id
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get account ID: {str(e)}")
            raise
    
    def create_draft(self, 
                    to_email: str, 
                    subject: str, 
                    content: str,
                    from_email: str) -> Dict:
        """Create a draft email in Zoho Mail and update leads sheet"""
        
        account_id = self.get_account_id()
        url = f"https://mail.zoho.com/api/accounts/{account_id}/messages"
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.get_access_token()}",
            "Content-Type": "application/json"
        }
        
        data = {
            "fromAddress": from_email,
            "toAddress": to_email,
            "subject": subject,
            "content": content,
            "mode": "draft",
            "mailFormat": "html"
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            # Update leads sheet to mark as emailed
            update_lead_emailed_status(self.service, self.spreadsheet_id, to_email)
            
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to create draft for {to_email}: {str(e)}")
            raise

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
    
    # Check if email exists and has been emailed
    for row in existing_data[1:]:  # Skip header row
        if len(row) > email_index and row[email_index] == email:
            if len(row) > emailed_index and row[emailed_index].lower() == 'true':
                return True
    
    return False

def create_multiple_drafts(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    contacts: List[Tuple[str, str]],
    from_email: str
) -> None:
    """
    Create draft emails for a list of contacts
    
    Args:
        client_id: Zoho API client ID
        client_secret: Zoho API client secret
        refresh_token: Zoho API refresh token
        contacts: List of (website, email) tuples
        from_email: Sender email address
    """
    
    zoho = ZohoMailAPI(client_id, client_secret, refresh_token)
    
    for website, email in contacts:
        try:
            # Check if already emailed
            if check_if_already_emailed(zoho.service, zoho.spreadsheet_id, email):
                logging.info(f"Skipping {email} - already emailed")
                continue
                
            # Create a browser session to get website content
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            })
            
            try:
                # Get website content
                response = session.get(website, timeout=30)
                response.raise_for_status()
                page_content = response.text
                
                # Create customized email
                subject, content = create_customized_email(website, email, page_content)
                
                # Create draft
                zoho.create_draft(
                    to_email=email,
                    subject=subject,
                    content=content,
                    from_email=from_email
                )
                
                logging.info(f"Created customized draft for {email} ({website})")
                
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to fetch website {website}: {str(e)}")
                # Mark as emailed so we don't try again
                update_lead_emailed_status(zoho.service, zoho.spreadsheet_id, email)
                logging.info(f"Marked {email} as emailed due to website fetch failure")
            
        except Exception as e:
            logging.error(f"Failed to create draft for {email}: {str(e)}")
            # Mark as emailed for any other failures
            try:
                update_lead_emailed_status(zoho.service, zoho.spreadsheet_id, email)
                logging.info(f"Marked {email} as emailed due to processing failure")
            except Exception as update_error:
                logging.error(f"Failed to mark {email} as emailed: {str(update_error)}")
            continue
