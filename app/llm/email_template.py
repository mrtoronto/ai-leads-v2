import os
from app.utils.template_cache import load_templates_from_cache

# Default business context - will be replaced by cached version if available
DEFAULT_ZAKAYA_CONTEXT = """
Zakaya is a community platform that helps organizations:
1. Create spaces for meaningful member interactions
2. Increase participation in events and activities
3. Help members feel more connected and less lonely
4. Make it easy for staff to engage with the community

Key features:
- Text and voice chat rooms for different topics
- Event calendar for coordinating activities
- Buddy matching to help members connect
- Simple tools for staff to manage and engage
"""

# Base HTML template with standard formatting
BASE_EMAIL_TEMPLATE = """
<div style="font-family: Calibri, 'Segoe UI', Arial, sans-serif; font-size: 12pt; line-height: 1.2; color: #000000;">
    <p style="margin: 0 0 1em 0;">Hello!</p>

    {custom_intro}

    {main_pitch}

    <ul style="margin: 1em 0 1em 0; padding-left: 20px;">
        {key_points}
    </ul>

    {custom_closing}

    <p style="margin: 0 0 1em 0;">Talk soon!<br><br>
    Matt Toronto — Founder<br>
    <a href="https://zakaya.io?utm_channel=lead_email&utm_source={safe_name}" style="font-weight: bold; text-decoration: underline; color: #0066cc;">Zakaya</a> | <a href="https://twitter.com/matttoronto" style="font-weight: bold; text-decoration: underline; color: #0066cc;">Twitter</a></p>
</div>
"""

# Default template - we'll use a single template focused on community value
DEFAULT_EMAIL_TEMPLATES = {
    "community": {
        "extra_context": "We help organizations build engaged online communities where members feel connected and supported. Our focus is on creating meaningful interactions that reduce loneliness and increase participation.",
        "subject": "Community Platform for {business_name}",
        "main_pitch": "<p style=\"margin: 0 0 1em 0;\">Zakaya helps create <span style=\"font-weight: bold;\">active online communities</span> where members feel connected and supported.</p>"
    }
}

# Load cached data
cached_data = load_templates_from_cache()

# Set up email templates and context from cache or defaults
if cached_data and 'context' in cached_data:
    ZAKAYA_CONTEXT = cached_data['context']
    EMAIL_TEMPLATES = {k: v for k, v in cached_data.items() if k != 'context'}
else:
    ZAKAYA_CONTEXT = DEFAULT_ZAKAYA_CONTEXT
    EMAIL_TEMPLATES = DEFAULT_EMAIL_TEMPLATES

def get_email_content(template_key: str, safe_name: str, custom_intro: str, custom_main_pitch: str, key_points: str, custom_closing: str, lead_url: str) -> str:
    """
    Generate email content using the base template and customizations
    
    Args:
        template_key: Key of the template to use
        custom_intro: Customized introduction
        key_points: HTML formatted key points
        custom_closing: Customized closing
        
    Returns:
        Complete email content
    """
    # Ensure custom sections have proper styling
    if not custom_intro.startswith('<p style='):
        custom_intro = f'<p style="margin: 0 0 1em 0;">{custom_intro}</p>'
    if not custom_closing.startswith('<p style='):
        custom_closing = f'<p style="margin: 0 0 1em 0;">{custom_closing}</p>'
    
    # Add styling to key points if needed
    if '<span style="font-weight: bold;">' not in key_points:
        key_points = key_points.replace('<span class=\'highlight\'>', '<span style="font-weight: bold;">')
    
    template = EMAIL_TEMPLATES[template_key]
    return BASE_EMAIL_TEMPLATE.format(
        safe_name=safe_name,
        custom_intro=custom_intro,
        main_pitch=custom_main_pitch,
        key_points=key_points,
        custom_closing=custom_closing,
        lead_url=lead_url
    )