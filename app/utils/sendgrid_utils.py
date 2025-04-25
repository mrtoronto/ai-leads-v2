from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From
import logging
from app.local_settings import SENDGRID_API_KEY

logger = logging.getLogger('ZAKAYA')

def send_email_via_sendgrid(subject, sender, recipients, html_body, text_body=None, bcc=None):
    """
    Send an email using SendGrid API
    
    Args:
        subject: Email subject
        sender: Sender email or tuple of (email, name)
        recipients: Recipient email or list of emails
        html_body: HTML content
        text_body: Plain text content (optional)
        bcc: BCC recipients (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    if isinstance(sender, tuple):
        sender = From(sender[0], sender[1])
    
    message = Mail(
        from_email=sender,
        to_emails=recipients,
        subject=subject,
        html_content=html_body
    )
    
    # Add plain text content only if provided
    if text_body:
        message.plain_text_content = text_body

    if bcc:
        message.bcc = bcc

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Email sent via SendGrid. Status Code: {response.status_code}")
        return True
    except Exception as e:
        logger.error(f"Error sending email via SendGrid: {str(e)}")
        return False 