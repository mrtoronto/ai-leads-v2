ZAKAYA_CONTEXT = """
1. Unique Community Dynamics: Emphasize Zakaya's ability to replicate real-life social dynamics online, creating a sense of belonging and community that is often missing in traditional online platforms. This can be particularly appealing to businesses that value strong customer relationships and community loyalty.
2. Targeted Community Engagement: Highlight how Zakaya's dense micro-communities can lead to increased engagement and interaction among members. This is crucial for businesses that rely on active participation, such as educational institutions, hobby groups, or professional networks.
Retention and Loyalty: Stress the potential for Zakaya to improve customer retention and loyalty by fostering a community where members feel connected and valued. This can be a key selling point for subscription-based services or membership organizations.
4. Comprehensive Feature Set: Detail the app's features, such as chat rooms, content feeds, event calendars, and the buddy match program, which are designed to facilitate interaction and engagement. These features can be tailored to meet the specific needs of different types of communities, from social clubs to professional networks.
5. Onboarding and Integration: The buddy match program not only helps new members integrate quickly but also encourages ongoing interaction, which can be a significant advantage for businesses looking to enhance their onboarding process and ensure new members feel welcomed and engaged.
Feedback-Driven Development: Zakaya's commitment to incorporating user feedback into its development process can be a major draw for potential users who value a platform that listens and adapts to their needs. This can be particularly appealing to tech-savvy audiences or those who have been frustrated by unresponsive platforms in the past.
7. Transparency and Trust: The visible progress of feedback and feature requests in the global chat room can build trust with users, showing that their input is valued and acted upon. This transparency can differentiate Zakaya from competitors and foster a more engaged and loyal user base.
Scalability and Customization: Highlight Zakaya's potential to scale and customize communities to fit the unique needs of different businesses or groups. Whether it's a small local business or a large organization, Zakaya can adapt to support their community-building goals.
9. Event and Activity Coordination: The app's event calendar and activity feed can help businesses coordinate events and activities more effectively, ensuring higher participation rates and better community involvement.
Potential for Cross-Promotion: Businesses can use Zakaya to cross-promote events, products, or services within the community, leveraging the dense network of connections to reach a wider audience.
By incorporating these refined points into your outreach strategy, you can provide a comprehensive and compelling case for why potential users should consider adopting Zakaya for their community-building needs.
"""


# Base HTML template with standard formatting
BASE_EMAIL_TEMPLATE = """
<div style="font-family: Calibri, 'Segoe UI', Arial, sans-serif; font-size: 12pt; line-height: 1.2; color: #000000;">
    <p style="margin: 0 0 1em 0;">Hello!!</p>

    {custom_intro}

    {main_pitch}

    <ul style="margin: 0 0 1em 0; padding-left: 20px;">
        {key_points}
    </ul>

    {custom_closing}

    <p style="margin: 0 0 1em 0;">Best,<br><br>
    —<br><br>
    Matt Toronto, Founder<br>
    <a href="https://zakaya.io?utm_channel=lead_email&utm_source={safe_name}" style="font-weight: bold; text-decoration: underline; color: #0066cc;">Zakaya</a> | <a href="https://twitter.com/matttoronto" style="font-weight: bold; text-decoration: underline; color: #0066cc;">Twitter</a></p>

    <a href="{lead_url}" style="font-weight: bold; text-decoration: underline; color: #0066cc;">{lead_url}</a>
</div>
"""

# Email templates dictionary with just the variable content
EMAIL_TEMPLATES = {
    "coworking": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their physical space. This should increase regular attendance, engagement with the space, retention and revenue.",
        "subject": "Digital Third Place for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">With Zakaya, we could create a <span style="font-weight: bold;">digital third place</span> for your coworking community that complements your physical space!</p>"""
    },
    "event_space": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their events and venue. This should increase attendance, engagement, retention and revenue.",
        "subject": "Community Platform for {business_name} Events",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help create a <span style="font-weight: bold;">vibrant online community</span> around your events and venue!</p>"""
    },
    "community_center": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their physical space. This should increase event attendance, community engagement, member retention and revenue.",
        "subject": "Digital Community Hub for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help extend your community's reach with a <span style="font-weight: bold;">dedicated digital space</span> that brings people together!</p>"""
    },
    "fitness_center": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their fitness programs and classes. This should increase class attendance, member motivation, accountability, and retention.",
        "subject": "Digital Fitness Community for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could transform your fitness center into a <span style="font-weight: bold;">24/7 motivational community</span> that keeps members engaged between workouts!</p>"""
    },
    "art_studio": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their art workshops and exhibitions. This should increase workshop participation, art sales, and student engagement.",
        "subject": "Creative Community Platform for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help build an <span style="font-weight: bold;">inspiring creative community</span> that connects your artists beyond the studio!</p>"""
    },
    "brewery": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their brewery events, tastings, and releases. This should increase event attendance, customer loyalty, and brand engagement.",
        "subject": "Craft Beer Community for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help create a <span style="font-weight: bold;">passionate community</span> of craft beer enthusiasts around your brewery!</p>"""
    },
    "music_venue": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their music events and performances. This should increase ticket sales, fan engagement, and venue loyalty.",
        "subject": "Music Community Platform for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help build an <span style="font-weight: bold;">engaged music community</span> that keeps the energy going between shows!</p>"""
    },
    "wellness_center": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their wellness programs and workshops. This should increase program participation, client support, and holistic engagement.",
        "subject": "Wellness Community Hub for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help create a <span style="font-weight: bold;">supportive wellness community</span> that nurtures growth beyond sessions!</p>"""
    },
    "bookstore": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their book events, reading groups, and author visits. This should increase event attendance, book sales, and reader engagement.",
        "subject": "Reader Community Platform for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help create a <span style="font-weight: bold;">vibrant reading community</span> that extends beyond your shelves!</p>"""
    },
    "farm": {
        "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their seasonal events, farm-to-table experiences, and educational programs. This should increase visitor engagement, product sales, and community support.",
        "subject": "Farm Community Hub for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help cultivate a <span style="font-weight: bold;">thriving farm community</span> that connects people to local agriculture!</p>"""
    },
    "community_garden": {
        "extra_context": "We are looking to sell these organizations on the idea of creating an online community around their gardening activities, workshops, and volunteer programs. This should increase participation, knowledge sharing, and community involvement.",
        "subject": "Digital Garden Community for {business_name}",
        "main_pitch": """<p style="margin: 0 0 1em 0;">Zakaya could help grow a <span style="font-weight: bold;">flourishing garden community</span> that connects green thumbs year-round!</p>"""
    }
}

def get_email_content(template_key: str, safe_name: str, custom_intro: str, key_points: str, custom_closing: str, lead_url: str) -> str:
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
        main_pitch=template["main_pitch"],
        key_points=key_points,
        custom_closing=custom_closing,
        lead_url=lead_url
    )