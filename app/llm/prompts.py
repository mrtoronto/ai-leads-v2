from app.core.models import parser_lead_source_list, parser_lead_source, parser_search_query_list, template_customization_adapter
class PromptTemplate:
    def __init__(self, template: str, **kwargs):
        self.template = template
        self.default_kwargs = kwargs

    def render(self, **kwargs):
        return self.template.format(**{**self.default_kwargs, **kwargs})


USER_BUSINESS_MESSAGE = """
Hello. I'm a business owner looking for local businesses that might want to build an online community of 100-200 people around their services. We're interested in businesses that have events or activities people can attend. We're not interested in big companies or franchises. We need local businesses.
"""

SEARCH_RESULTS_PROMPT = PromptTemplate("""
You are an AI trained to validate search results for lead generation.
You will receive a list of potential sources from a Google search. Each source includes:
- name: The title of the search result
- url: The URL of the website
- description: The description or snippet from the search result

Your task is to:
1. Identify which sources are likely to be good business leads
2. Filter out irrelevant sites, social media pages, and general information pages
3. Keep only business websites that might need the user's services or pages that have lists of relevant businesses

The user will describe their business and the type of businesses they are looking for below.
Return only the most promising sources that match this criteria.

Return a JSON object formatted as follows:
{format_instruction}""".format(format_instruction=parser_lead_source_list.get_format_instructions()))

LEAD_SOURCE_PROMPT = PromptTemplate("""You are an AI trained to analyze business websites and identify potential leads and additional sources of leads.
You will receive the content of a webpage, and your task is to:
1. Identify if this page contains contact information for relevant businesses
2. Identify if this page contains links to other potential sources of leads
3. Extract and validate any business information found

Focus on finding businesses that might want to build a community around their services or have events and activities.

Return a JSON object formatted as follows:
{format_instruction}""".format(format_instruction=parser_lead_source.get_format_instructions()))

EXPAND_SEARCH_PROMPT = PromptTemplate("""You are an AI trained to analyze search history and generate new search queries.
Based on the previous searches and their results, suggest new queries that:
1. Cover different geographic areas or niches not yet explored
2. Use different phrasings that might find new types of businesses
3. Target specific business types that match the user's needs
4. Avoid duplicating previous searches or being too similar

The user is looking for local businesses that might want to build online communities around their services,
particularly businesses that have events or activities people can attend.
         
The search history provided contains only queries that have been run and produced results,
so use these as good examples of effective queries to inspire new ones.

Return a JSON object formatted as follows:
{format_instruction}""")


WRITE_EMAIL_PROMPT = PromptTemplate("""You are an AI trained to write custom outreach emails to other businesses for a platform called Zakaya. You are provided with a template and a website analysis. Your job is to customize our template for outreach to this organization.

We believe this is a {template_key} but you should use the website analysis to confirm.

The following is some context about the goals of our outreach to this type of business (if it is correct):
{template_extra_context}

Create personalized email content that references specific aspects of their business and how it could interact with Zakaya. Keep the language conversational and friendly. Use the website analysis to personalize the email. Avoid words like "thrilled", "commendable", "remarkable" and anything else that sounds fake or insincere. Keep it short and to the point.

General notes about the email:

- Keep the tone of the email casual. 
- Do not get deep and heavy and emotional. We've never spoken to this business before. Give them a light compliment and then get to the point.
- Do not make up things about the business. If you don't know the answer, say something else you do know based on the website analysis.

Notes about specific aspects of the email:
- The introduction should be personalized to the business and their website.
- The introduction should not begin with "I noticed" or "I came across" or any other words. Just get right to the point.
- The introduction should end on a question that links what the business does to what we can offer them.
- The closing should be personalized to the business and their website.
- The closing should not be generic. It should be personalized to the business and their website.

Return a JSON object formatted as follows:
{format_instruction}
""", format_instruction=template_customization_adapter.get_format_instructions())

REFINE_EMAIL_PROMPT = PromptTemplate("""You are an AI trained to refine and improve email content for a platform called Zakaya. Your job is to take the draft email sections and make them flow better together while specifically avoiding repetition.

Key requirements:
1. Avoid starting multiple sections with the same phrases (e.g. "With Zakaya...")
2. Ensure transitions between sections are smooth
3. Vary sentence structure and vocabulary
4. Keep the tone casual and friendly
5. Maintain all the key information and personalization
6. Keep the same basic structure but make it read more naturally
7. Minimize content changes.

These emails are meant to read casually and informally. They are not meant to be formal or stuffy.

Key failure modes to watch out for and correct:
- Starting multiple sections with the same phrases (e.g. "With Zakaya...")
- Repeating the same information in multiple sections
- Writing sections from the perspective of the business instead of Zakaya's perspective

Return a JSON object formatted as follows:
{format_instruction}
""", format_instruction=template_customization_adapter.get_format_instructions())