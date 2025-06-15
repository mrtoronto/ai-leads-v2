from app.core.models import parser_lead_source_list, parser_lead_source, parser_search_query_list, template_customization_adapter
class PromptTemplate:
    def __init__(self, template: str, **kwargs):
        self.template = template
        self.default_kwargs = kwargs

    def render(self, **kwargs):
        return self.template.format(**{**self.default_kwargs, **kwargs})


USER_BUSINESS_MESSAGE = """
Hello. I'm a business owner looking for local businesses and organizations that might want to build an online community of 100-200 people around their services or activities. 

We're interested in businesses that:
- Have events, activities, classes, or collaborative projects that people can attend
- Foster community connections (makerspaces, creative spaces, coworking spaces, community centers, etc.)
- Serve local communities rather than being large corporations or franchises
- Would benefit from having an online platform to connect their members/customers

This includes makerspaces, art studios, coworking spaces, community centers, educational organizations, hobby groups, and similar community-focused businesses.
"""

SEARCH_RESULTS_PROMPT = PromptTemplate("""
You are filtering Google search results to find potential business leads.

The user is looking for local businesses and organizations that:
- Host events, activities, classes, or collaborative projects
- Foster community connections (makerspaces, creative spaces, coworking, community centers)
- Serve local communities (not large corporations or franchises)
- Would benefit from an online platform to connect their members/customers

Your task:
1. Review each search result (name, url, description)
2. BE VERY INCLUSIVE - err on the side of keeping results
3. KEEP any result that:
   - Mentions a specific business, organization, or venue
   - Lists or describes businesses (even blog posts about businesses)
   - Represents any kind of community space or activity center
   - Could potentially host events or activities
   
4. ONLY EXCLUDE these specific types:
   - Pure directory sites with no specific business info (Yelp search pages, Yellow Pages)
   - Social media profile lists (not individual business profiles)
   - Government websites (.gov)
   - Wikipedia or other encyclopedias
   - Large corporations (Amazon, Walmart, etc.)

Important: When in doubt, ALWAYS INCLUDE. We want to cast a wide net and would rather have false positives than miss opportunities.

Examples to KEEP:
- "5 Kid-Friendly Makerspaces in Philadelphia" → Blog listing actual businesses
- "HANDWORK HOUSE - Updated June 2025" → Specific business
- "NextFab: Makerspace Philadelphia" → Makerspace business
- "Art Class Kids Makerspace" → Specific program/business
- "Get Creative at these 17 DIY Classes" → Lists actual businesses

Examples to EXCLUDE:
- "Yelp.com/search?makerspaces" → Directory search page
- "Wikipedia: List of makerspaces" → Encyclopedia
- "Amazon.com" → Large corporation

Return a JSON object formatted as follows:
{format_instruction}""")

LEAD_SOURCE_PROMPT = PromptTemplate("""You are an AI trained to analyze business websites and identify potential leads and additional sources of leads.
You will receive the content of a webpage, and your task is to:
1. Identify if this page contains contact information for relevant businesses
2. Identify if this page contains links to other potential sources of leads
3. Extract and validate any business information found

Focus on finding businesses that might want to build a community around their services or have events and activities.

Return a JSON object formatted as follows:
{format_instruction}""")

EXPAND_SEARCH_PROMPT = PromptTemplate("""You are an AI trained to analyze search history and generate new search queries.
Based on the previous searches and their results, suggest new queries that:
1. Cover different geographic areas or niches not yet explored
2. Use different phrasings that might find new types of businesses
3. Target specific business types that match the user's needs
4. Avoid duplicating previous searches or being too similar

The user is looking for local businesses that might want to build online communities around their services,
particularly businesses that have events or activities people can attend.
                                      
If the user provides additional context, use it to generate new queries. Follow the additional context closely. If it is not provided, use the user's business message to generate new queries.
         
The search history provided contains only queries that have been run and produced results,
so use these as good examples of effective queries to inspire new ones.

Return a JSON object formatted as follows:
{format_instruction}""")


WRITE_EMAIL_PROMPT = PromptTemplate("""You are writing a friendly, conversational outreach email for Zakaya, a community platform. Write like a real person who shares their passion for community building and sees a potential partnership opportunity.

Context about our value proposition:
{template_extra_context}

IMPORTANT: Zakaya is a flexible community infrastructure platform designed for small-medium sized organizations that want to build stronger communities. We're looking for our first partner organizations who are excited about community building. The platform exists - we just need the right communities to bring it to life.

Create an email that:
1. Opens by connecting with their community-building efforts - show you understand and share their values.
2. Demonstrates you've researched their work by mentioning something specific from their website.
3. Positions Zakaya as a community platform that works particularly well for organizations like theirs.
4. Sounds like someone reaching out about a shared interest, not selling a product.
5. Keeps it brief and conversational.
6. Makes it clear we're looking for organizations excited to be early adopters.

Email structure:
- Opening: Connect with their community-building mission or impact. Start with shared values or genuine interest in their approach.
- Main message: Explain that Zakaya is a community platform that works well for organizations who care about community connection and we're looking for the right partners.
- Features: Present 3-4 specific features with clear explanations of how this organization could use them.
- Wrap-up: Express interest in exploring possibilities together as an early partner.

ZAKAYA'S CORE FEATURES (be explicit about these):
1. Communication Rooms: Chat rooms, voice chat, media sharing rooms, forums, and content feeds
2. Event Management: Event calendar with RSVP system and dedicated rooms for each event
3. Buddy Matching: Automated system that pairs small groups within the community regularly
4. Staff Tools: Direct channels for staff to connect with and update the community

Feature presentation guidelines:
- NAME the feature type explicitly (don't just describe what it does)
- Connect each feature to their specific use case
- Be concrete about functionality
- Format: "[Feature name]: [How they'd use it]"

Example feature descriptions:
- "Chat rooms and forums where your [specific audience] can [specific activity relevant to them]"
- "An event calendar with RSVP system - perfect for your [specific events], plus each event gets its own dedicated discussion room"
- "Our buddy matching system regularly pairs small groups of your members based on [relevant criteria for their org]"
- "Direct communication channels for your staff to share [specific type of updates] with the community"

Key phrasing guidelines:
- For the platform/features: Use present tense - "Zakaya provides", "you get", "includes"
- For the partnership: Use aspirational language - "we're looking for", "we'd love to partner with"
- Position Zakaya as a flexible platform that works well for various organization types, including theirs
- Avoid implying Zakaya was built specifically for their organization type
- Position them as an ideal early adopter who could help us learn what works best for organizations like theirs
- Emphasize we're offering this to select organizations who share our vision

CORRECT positioning language:
- "Zakaya is a community platform that works particularly well for organizations like yours..."
- "We built Zakaya as flexible community infrastructure that organizations can adapt to their needs..."
- "The platform is designed to work for various types of community-focused organizations, including [their type]..."
- "Zakaya provides the community infrastructure that organizations like yours need to..."

AVOID these positioning phrases:
- "designed for [specific org type] like yours"
- "built specifically for [org type]"
- "created for organizations like yours"
- Any language that implies Zakaya was made exclusively for their organization type

Opening strategies (avoid "I noticed" or passive observations):
- Connect through shared values: "Your approach to building community through [specific activity] is exactly the kind of work we want to support with Zakaya..."
- Start with their impact: "The way [Organization] connects communities through [activity] shows the kind of community-focused work that Zakaya was built to support..."
- Lead with genuine interest: "I've been researching organizations that create meaningful community connections, and your [specific program/approach] is exactly what our platform is designed to help..."
- Focus on their mission: "Your commitment to [specific community goal] is exactly the kind of passion we want to support at Zakaya..."

Writing style:
- Write like you're reaching out to a potential partner, not a customer.
- Show enthusiasm for community building without being over the top.
- Be specific but keep compliments modest and believable.
- Demonstrate understanding of their work and values.
- Sound like someone who genuinely cares about community connection.
- Be clear that while the platform is ready, we're selective about partnerships.

NEVER use these words/phrases:
- "genuinely impressed"
- "unwavering dedication"
- "truly"
- "vibrant"
- "fantastic"
- "remarkable"
- "evidently"
- "elevate"
- "amazing"
- "While browsing online, I found..."
- "I came across..."
- "I was looking into..."
- "I noticed..." (as an opening)
- "cool" (unless writing to very casual organizations)
- "nice connections" or "nice" as a descriptor
- "we're building/developing" (for features - they're already built)
- "imagine if" or "what if" (for features - they exist)
- "dedicated spaces" (too vague - name the actual feature)
- "founding partners", "equity partners", "co-founders" (too much commitment implied)
- "designed for [org type] like yours" (implies built specifically for them)

Instead, use appropriate partnership language:
- "one of our early communities"
- "bring your community to Zakaya"
- "create a community on our platform"
- "be one of the first organizations to use Zakaya"
- "help us understand what works best for organizations like yours"
- "works particularly well for organizations like yours"
- "perfect fit for the kind of community work you do"

Tone guidelines by organization type:
- Symphony/Orchestra: "bringing communities together through classical music" not "cool performances"
- Theater: "creating shared experiences that build community" not "nice shows"
- Museum: "connecting people through cultural experiences" not "cool exhibits"
- Sports teams: "building community through teamwork" not "nice games"
- Educational: "fostering collaborative learning communities" not "cool classes"

Remember: You're looking for organizations that are passionate about community building and would be excited to be among the first to use a flexible community platform designed for their needs. The platform is ready and works for various organization types - we just need the right partners who share our vision for community connection.

Return a JSON object formatted as follows:
{format_instruction}
""")

REFINE_EMAIL_PROMPT = PromptTemplate("""You're editing email drafts to make them sound more engaging and partnership-focused. The goal is to make emails sound like they're from someone who shares the organization's passion for community building and sees potential for collaboration.

CRITICAL: Zakaya is a flexible community infrastructure platform that works for various organization types. We're looking for early partner organizations. Fix any language that implies Zakaya was built specifically for their organization type. BE EXPLICIT about feature names.

Key editing tasks:
1. REMOVE these banned words/phrases completely:
   - truly, genuinely, evidently
   - vibrant, fantastic, remarkable, amazing
   - unwavering, dedication
   - elevate
   - any phrase that sounds like corporate marketing speak
   - "cool" when addressing formal organizations (orchestras, museums, universities)
   - "nice" as a weak descriptor (nice connections, nice events)
   - "I noticed..." as an opening (too passive)
   - "I came across..." or "I found..." (sounds random)
   - "we're building/developing" when referring to features (they're already built)
   - "imagine if" or "what if" for features (they exist - use present tense)
   - "dedicated spaces" (too vague - specify chat rooms, forums, etc.)

2. Fix misleading positioning language:
   
   BAD (implies Zakaya was built specifically for them):
   - "designed for [org type] like yours"
   - "built specifically for [org type]"
   - "created for organizations like yours" 
   - "platform designed for cultural centers like yours"
   
   GOOD (accurate positioning):
   - "community platform that works particularly well for organizations like yours"
   - "flexible community infrastructure that organizations like yours can adapt"
   - "platform designed to work for various types of community-focused organizations, including yours"
   - "provides the community infrastructure that organizations like yours need"

3. Fix vague feature descriptions - BE EXPLICIT:
   
   BAD (vague descriptions):
   - "Dedicated spaces where..." → "Chat rooms and forums where..."
   - "Your calendar becomes a hub..." → "Event calendar with RSVP system where..."
   - "Connect with newcomers..." → "Our buddy matching system pairs..."
   - "Tools for staff..." → "Direct communication channels for your staff..."
   - "Spaces to share..." → "Media rooms and content feeds for sharing..."
   
   GOOD (explicit feature names):
   - "Chat rooms, voice chat, and forums where your members can..."
   - "Event calendar with RSVP functionality - each event gets its own discussion room..."
   - "Our buddy matching system regularly pairs small groups of members..."
   - "Direct channels for your staff to share updates with the community..."

4. ZAKAYA'S FEATURES (always mention these explicitly):
   - Communication: Chat rooms, voice chat, media rooms, forums, content feeds
   - Events: Event calendar with RSVP system + dedicated rooms per event
   - Buddy Matching: Automated pairing system for small groups
   - Staff Tools: Direct communication channels between staff and community

5. Fix feature language (use present tense - features exist):
   
   BAD (sounds like features are in development):
   - "We're developing chat rooms..." → "Chat rooms where participants can..."
   - "We're building buddy matching..." → "Our buddy matching system pairs..."
   - "Imagine if your event calendar..." → "Your event calendar with RSVP system..."
   - "What if your staff could..." → "Your staff can share updates..."
   
   GOOD (shows features are ready):
   - "Zakaya includes [specific feature]..."
   - "You get access to [specific feature]..."
   - "The platform provides [specific feature]..."

6. Fix partnership language (this is what's aspirational):
   
   BAD (implies we have many partners):
   - "Organizations use Zakaya to..." → "Your organization could use Zakaya to..."
   - "Our partners love..." → "We're looking for organizations that would love..."
   - "We help organizations..." → "We'd love to help organizations like yours..."
   
   BAD (implies too much commitment):
   - "founding partners" → "one of our early communities"
   - "equity partners" → "early adopters"
   - "co-founders" → "first organizations to join"
   - "help shape the platform" → "help us learn what works best"
   
   GOOD (shows we're seeking communities):
   - "We're looking for organizations like yours to bring their community to Zakaya..."
   - "We'd love to have your community on our platform..."
   - "We're excited to offer this to select organizations..."
   - "As one of our early communities, you could..."
   - "Would you be interested in creating a community on Zakaya?"

7. Fix weak openings by focusing on shared values:
   
   BAD openings to replace:
   - "I noticed that you..." → "Your approach to building community through..."
   - "I saw that you..." → "The way you bring people together..."
   - "I came across your organization..." → "Your commitment to [specific mission]..."
   
   GOOD openings that connect:
   - "Your approach to building community through [specific activity] is exactly the kind of work we want to support with Zakaya..."
   - "The way the [Organization] connects communities through [activity] shows the kind of community-focused work that Zakaya was built to support..."

Example transformations:
BAD: "Zakaya is a community platform designed for cultural centers like yours..."
GOOD: "Zakaya is a community platform that works particularly well for community-focused organizations like yours..."

BAD: "We built Zakaya specifically for makerspaces..."
GOOD: "Zakaya provides the community infrastructure that makerspaces like yours need to..."

BAD: "Dedicated spaces where your students can share recordings and discuss practice techniques..."
GOOD: "Chat rooms and content feeds where your students can share recordings, plus forums for discussing practice techniques..."

BAD: "Your workshop calendar becomes a central hub where members can see who's attending..."
GOOD: "Event calendar with RSVP system for your workshops - members can see who's attending, and each workshop gets its own discussion room..."

BAD: "Connect experienced students with newcomers..."
GOOD: "Our buddy matching system pairs experienced students with newcomers based on their instruments and skill levels..."

BAD: "Your instructors can share performance tips..."
GOOD: "Direct communication channels where your instructors can share performance tips and music theory insights with the student community..."

BAD: "Would you be interested in being one of our founding partners?"
GOOD: "Would you be interested in bringing your community to Zakaya?"

Remember: Zakaya is a flexible community infrastructure platform that works for various organization types. Be explicit about feature names. We're looking for the right organizations who are passionate about community building to be our early partners. Never imply the platform was built specifically for their organization type.

Return a JSON object formatted as follows:
{format_instruction}
""")