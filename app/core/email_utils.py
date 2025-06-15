import requests
import re
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Tuple, Optional
import logging

from app.llm.llm import _llm
from app.llm.email_template import EMAIL_TEMPLATES, get_email_content, ZAKAYA_CONTEXT
from app.llm.prompts import WRITE_EMAIL_PROMPT, REFINE_EMAIL_PROMPT
from app.core.models import (
    WebsiteAnalysis, 
    TemplateSelection, 
    TemplateCustomization, 
    website_analysis_adapter, 
    template_selection_adapter, 
    template_customization_adapter
)
from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.utils.sheet_cache import get_sheet_data_cached, update_cache_after_write

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

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
        content = _llm(messages, model_name='gpt-4o', temp=0.1)
        if content:
            return website_analysis_adapter.parse(content)
        else:
            logging.error("LLM returned None response")
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
        content = _llm(messages, model_name='gpt-4o', temp=0.1)
        if content:
            # Parse the JSON content directly
            return template_selection_adapter.parse(content)
        else:
            logging.error("LLM returned None response")
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
    Customize the template based on website analysis
    
    Args:
        template_key: Key of the selected template
        analysis: WebsiteAnalysis object
        
    Returns:
        TemplateCustomization object with customization details
    """
    template = EMAIL_TEMPLATES[template_key]
    
    messages = [
        {
            "role": "system", 
            "content": WRITE_EMAIL_PROMPT.render(
                template_extra_context=template["extra_context"],
                format_instruction=template_customization_adapter.get_format_instructions()
            )
        },
        {"role": "user", "content": f"For context, here is some context about Zakaya:\n{ZAKAYA_CONTEXT}"},
        {"role": "user", "content": f"Please customize the template based on this analysis:\n{analysis.model_dump_json()}"}
    ]
    
    try:
        content = _llm(messages, model_name='claude-opus-4-20250514', temp=0.3)
        if content:
            # Parse the JSON content directly
            customization = template_customization_adapter.parse(content)
            
            # Set the main pitch from the template if not provided
            if not customization.custom_main_pitch:
                customization.custom_main_pitch = template["main_pitch"]
                
            return customization
        else:
            logging.error("LLM returned None response")
    except Exception as e:
        logging.error(f"Error customizing template: {str(e)}")
        # Return default customization
        return TemplateCustomization(
            safe_name=analysis.business_name.lower().replace(" ", "-"),
            subject_line=template["subject"].format(business_name=analysis.business_name),
            custom_intro="Your organization helps build meaningful connections in your community.",
            custom_main_pitch=template["main_pitch"],
            key_points=[
                "<span class='highlight'>Text and voice rooms</span> where members can share experiences and connect",
                "<span class='highlight'>Event calendar</span> to keep everyone informed about activities",
                "<span class='highlight'>Buddy matching</span> to help members find mentors and peers",
                "<span class='highlight'>Simple tools</span> for staff to engage with the community"
            ],
            custom_closing="Let me know if you'd like to see how this could work for your community.",
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
        content = _llm(messages, model_name='claude-opus-4-20250514', temp=0.3)
        if content:
            return template_customization_adapter.parse(content)
        else:
            logging.error("LLM returned None response")
            return customization  # Return original if LLM fails
    except Exception as e:
        logging.error(f"Error refining template customization: {str(e)}")
        return customization  # Return original if refinement fails

def create_customized_email(website: str, email: str, page_content: str, notes: str = "") -> Tuple[str, str]:
    """
    Create a customized email for a business based on their website content
    
    Args:
        website: Business website URL
        email: Recipient email address
        page_content: HTML content of the website
        notes: Notes about the lead (from the sheet)
        
    Returns:
        Tuple of (subject, content) for the email
    """
    try:
        # Analyze website, including notes in the context
        analysis = analyze_website_content_with_notes(website, page_content, notes)
        logging.info(f"Website analysis complete for {website}")
        
        # Get the single community template
        template = EMAIL_TEMPLATES["community"]
        
        # Create customization using notes
        customization = customize_template_with_notes("community", analysis, notes)
        
        # Refine the customization
        refined_customization = refine_template_customization(customization, analysis)
        
        # Format key points as HTML list items
        key_points_html = "".join([
            f"<li>{point}</li>"
            for point in refined_customization.key_points
        ])
        
        # Create email content using the helper function
        content = get_email_content(
            safe_name=refined_customization.safe_name,
            template_key="community",
            custom_intro=refined_customization.custom_intro,
            custom_main_pitch=refined_customization.custom_main_pitch,
            key_points=key_points_html,
            custom_closing=refined_customization.custom_closing,
            lead_url=website
        )
        
        # Create subject
        subject = template["subject"].format(business_name=analysis.business_name)
        if refined_customization.subject_line:  # Use custom subject if provided
            subject = refined_customization.subject_line
        
        return subject, content
        
    except Exception as e:
        logging.error(f"Error creating customized email: {str(e)}")
        
        # Get default template
        template = EMAIL_TEMPLATES["community"]
        
        # Create a safe name from the website
        safe_name = website.split("//")[-1].split("/")[0].replace(".", "-")
        
        # Extract business name from URL
        business_name = website.split("//")[-1].split("/")[0].split(".")[0].replace("-", " ").title()
        
        # Create default content
        key_points_html = "".join([
            f"<li style='margin-bottom: 0.5em;'>{point}</li>"
            for point in [
                "<span class='highlight'>Text and voice rooms</span> where members can share experiences and connect",
                "<span class='highlight'>Event calendar</span> to keep everyone informed about activities",
                "<span class='highlight'>Buddy matching</span> to help members find mentors and peers",
                "<span class='highlight'>Simple tools</span> for staff to engage with the community"
            ]
        ])
        
        content = get_email_content(
            safe_name=safe_name,
            template_key="community",
            custom_intro="<p style='margin: 0 0 1em 0;'>Your organization helps build meaningful connections in your community.</p>",
            custom_main_pitch=template["main_pitch"],
            key_points=key_points_html,
            custom_closing="<p style='margin: 0 0 1em 0;'>Let me know if you'd like to see how this could work for your community.</p>",
            lead_url=website
        )
        
        subject = template["subject"].format(business_name=business_name)
        
        return subject, content

def analyze_website_content_with_notes(url: str, page_content: str, notes: str) -> WebsiteAnalysis:
    """
    Analyze website content using LLM, including notes in the context.
    """
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

    max_content_length = 8000
    if len(page_content) > max_content_length:
        page_content = page_content[:max_content_length] + "..."

    # Always include notes context, even if empty
    notes_context = "No additional notes available." if not notes else f"Important context from our research:\n{notes}"

    messages = [
        {
            "role": "system",
            "content": f"""You are an AI trained to analyze business websites for lead generation for a platform called Zakaya.
Extract key information about the business that would be relevant for personalizing an email about a community platform. Focus on aspects related to community, events, and engagement.

IMPORTANT: You must incorporate insights from the provided research notes into your analysis.

Return a JSON object formatted as follows:
{website_analysis_adapter.get_format_instructions()}
"""
        },
        {"role": "user", "content": f"For context, here is some context about Zakaya:\n{ZAKAYA_CONTEXT}"},
        {
            "role": "user", 
            "content": f"""Please analyze this lead, incorporating both the research notes and website content.

RESEARCH NOTES:
{notes_context}

WEBSITE URL: {url}

WEBSITE CONTENT:
{page_content}"""
        }
    ]
    try:
        content = _llm(messages, model_name='gpt-4o-mini', temp=0.1)
        if content:
            return website_analysis_adapter.parse(content)
        else:
            logging.error("LLM returned None response")
    except Exception as e:
        logging.error(f"Error analyzing website: {str(e)}")
    return WebsiteAnalysis(
        summary="Could not analyze website",
        business_type="unknown",
        business_name=business_name,
        key_features=[],
        community_aspects=[],
        contact_person=None
    )

def customize_template_with_notes(template_key: str, analysis: WebsiteAnalysis, notes: str) -> TemplateCustomization:
    """
    Customize the template based on website analysis and notes.
    """
    template = EMAIL_TEMPLATES[template_key]
    
    # Always include notes context, even if empty
    notes_context = "No additional notes available." if not notes else f"Important context from our research:\n{notes}"
    
    messages = [
        {
            "role": "system", 
            "content": WRITE_EMAIL_PROMPT.render(
                template_extra_context=template["extra_context"],
                format_instruction=template_customization_adapter.get_format_instructions()
            ) + """

IMPORTANT GUIDELINES:
1. If the notes contain any personal connection points (e.g., being a fan, personal experience, etc.), these MUST be included naturally in the email, typically in the intro or closing.
2. When mentioning events, focus on how we enhance EXISTING events through social connection - we help dedicated members/fans get more value from events by experiencing them together.
3. Never make up personal connections that aren't in the notes.
4. Keep the tone personal - this is from Matt, the founder of Zakaya, reaching out personally."""
        },
        {"role": "user", "content": f"For context, here is some context about Zakaya:\n{ZAKAYA_CONTEXT}"},
        {
            "role": "user", 
            "content": f"""Please customize the template using both the research notes and website analysis.

RESEARCH NOTES:
{notes_context}

WEBSITE ANALYSIS:
{analysis.model_dump_json()}"""
        }
    ]
    
    try:
        content = _llm(messages, model_name='claude-opus-4-20250514', temp=0.3)
        if content:
            customization = template_customization_adapter.parse(content)
            
            # Set the main pitch from the template if not provided
            if not customization.custom_main_pitch:
                customization.custom_main_pitch = template["main_pitch"]
                
            return customization
        else:
            logging.error("LLM returned None response")
    except Exception as e:
        logging.error(f"Error customizing template: {str(e)}")
        return TemplateCustomization(
            safe_name=analysis.business_name.lower().replace(" ", "-"),
            subject_line=template["subject"].format(business_name=analysis.business_name),
            custom_intro="Your organization helps build meaningful connections in your community.",
            custom_main_pitch=template["main_pitch"],
            key_points=[
                "<span class='highlight'>Text and voice rooms</span> where members can share experiences and connect",
                "<span class='highlight'>Event calendar</span> to help members experience activities together",
                "<span class='highlight'>Buddy matching</span> to help members find others with shared interests",
                "<span class='highlight'>Simple tools</span> for staff to engage with the community"
            ],
            custom_closing="Let me know if you'd like to see how this could work for your community.",
            specific_references=[]
        ) 

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
        raise Exception(f"Failed to update emailed status: {str(e)}")

def check_if_already_emailed(service, spreadsheet_id: str, email: str) -> bool:
    """
    Check if an email has already been marked as emailed in the spreadsheet.
    If any instance is marked as emailed, update all instances to be marked as emailed.
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: ID of the spreadsheet
        email: Email address to check
        
    Returns:
        bool: True if already emailed, False otherwise
    """
    try:
        # Use cache instead of direct API call
        leads_df = get_sheet_data_cached(service, spreadsheet_id, 'leads')
        
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
                        service.spreadsheets().values().update(
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