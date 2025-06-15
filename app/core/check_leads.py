import asyncio
import random
from datetime import datetime
from app.llm.llm import _llm
from app.utils.browser import setup_browser
from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.utils.sheet_cache import get_sheet_data_cached
from app.core.models import LeadCheckResult
from langchain.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)

async def process_single_lead(context, service, spreadsheet_id, lead, i, total, semaphore):
    """Process a single lead to update contact info and generate notes"""
    url = lead.get('Link', '')
    if not url:
        print(f"Skipping lead {i}/{total} - no URL")
        return
        
    # Ensure URL has proper protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url.lstrip('/')
        
    print(f"\nProcessing lead {i}/{total}: {url}")
    
    async with semaphore:  # Use semaphore to limit concurrent requests
        try:
            page = await context.new_page()
            
            # Dictionary to store text content from different pages
            page_contents = {}
            
            # Function to safely get page content
            async def get_page_content(url, page_name):
                try:
                    # First try with networkidle, then fall back to domcontentloaded if that times out
                    try:
                        response = await page.goto(
                            url, 
                            wait_until='networkidle', 
                            timeout=30000  # Increase timeout to 30 seconds
                        )
                    except Exception as e:
                        if 'timeout' in str(e).lower():
                            print(f"Networkidle timeout for {page_name}, falling back to domcontentloaded...")
                            response = await page.goto(
                                url, 
                                wait_until='domcontentloaded', 
                                timeout=30000  # Increase timeout to 30 seconds
                            )
                        else:
                            raise
                    
                    if response and response.status < 400:
                        # Wait a bit longer for dynamic content
                        await page.wait_for_timeout(3000)
                        
                        # Get page content
                        content = await page.evaluate('() => document.body.innerText')
                        page_contents[page_name] = content
                        
                        # Get all navigation links and their text
                        links = await page.evaluate("""() => {
                            function isNavigationLink(element) {
                                // Check if element is in header, nav, or menu
                                const isInNav = element.closest('header, nav, [role="navigation"], [class*="menu"], [class*="nav"], [id*="menu"], [id*="nav"]');
                                return isInNav !== null;
                            }
                            
                            const allLinks = Array.from(document.querySelectorAll('a'));
                            return allLinks
                                .filter(link => {
                                    const href = link.href;
                                    // Only include links to same domain
                                    return href && 
                                           href.startsWith(window.location.origin) &&
                                           !href.includes('#') && // Exclude anchor links
                                           (isNavigationLink(link) || 
                                            link.innerText.toLowerCase().includes('contact') ||
                                            link.innerText.toLowerCase().includes('about'));
                                })
                                .map(link => ({
                                    text: link.innerText.trim(),
                                    href: link.href,
                                    isContact: link.innerText.toLowerCase().includes('contact'),
                                    isAbout: link.innerText.toLowerCase().includes('about')
                                }));
                        }""")
                        return links
                    elif response:
                        print(f"HTTP {response.status} error accessing {url}")
                        return []  # Other HTTP errors might be temporary
                    return []
                except Exception as e:
                    print(f"Error accessing {page_name} page: {str(e)}")
                    if 'net::ERR_NAME_NOT_RESOLVED' in str(e):
                        print("DNS resolution failed - domain may no longer exist")
                        return None  # DNS failure means domain is dead
                    elif 'Cannot navigate to invalid URL' in str(e):
                        print("Invalid URL format")
                        return None  # Invalid URL should be removed
                    return []  # Other errors might be temporary
            
            # Start with the provided URL
            try:
                # Extract base URL more safely
                parsed_url = url.split('//')[-1].split('/')
                base_url = 'https://' + parsed_url[0]
                
                # Get initial page content and links
                initial_links = await get_page_content(url, 'initial')
                if initial_links is None:  # Critical error occurred
                    # Remove the lead from the sheet
                    existing_data = get_sheet_data(service, spreadsheet_id, 'leads!A:J')
                    if not existing_data:
                        print("No data found in leads sheet")
                        return
                        
                    headers = existing_data[0]
                    rows = [headers]  # Start with headers
                    
                    # Keep all rows except the one with matching URL
                    url_index = headers.index('Link')
                    rows.extend([row for row in existing_data[1:] if row[url_index] != url])
                    
                    # Write back the filtered data
                    body = {'values': rows}
                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range='leads!A1',
                        valueInputOption='RAW',
                        body=body
                    ).execute()
                    
                    print(f"Removed lead with invalid URL: {url}")
                    return
                
                # Prioritize contact and about pages from navigation
                important_pages = []
                if initial_links:
                    contact_links = [link for link in initial_links if link['isContact']]
                    about_links = [link for link in initial_links if link['isAbout']]
                    
                    # Add unique links to important_pages
                    seen_urls = set()
                    for link in contact_links + about_links:
                        if link['href'] not in seen_urls:
                            important_pages.append(link)
                            seen_urls.add(link['href'])
                
                # Visit important pages
                for link in important_pages[:3]:  # Limit to 3 additional pages
                    await get_page_content(link['href'], f"nav_{link['text'].lower()}")
                
                # If we got no content, something's wrong
                if not page_contents:
                    print(f"Could not get any content from {url}")
                    return
                
                # Combine all page contents with headers
                combined_text = ""
                for page_name, content in page_contents.items():
                    combined_text += f"\n=== {page_name.upper()} PAGE ===\n{content}\n"
                
                # Setup Pydantic parser
                parser = PydanticOutputParser(pydantic_object=LeadCheckResult)
                
                # Process with LLM to extract contact info and generate notes
                messages = [
                    {"role": "system", "content": f"""You are an expert at analyzing business websites and extracting contact information and creating highly specific sales talking points.

Your task is to:
1. Find any phone numbers and email addresses on the page
2. Generate 2-3 highly specific talking points for a cold call about selling a digital community platform to this business

For the talking points, you MUST:
- Reference specific programs, classes, events, or services mentioned on their website
- Include actual names of their offerings (e.g. "Your 'Morning Flow' yoga class participants could connect...")
- Mention specific aspects of their business model or community that would benefit
- Make it clear you've read their website by citing specific details
- Keep each point focused and under 15 words
- Format each point with a bullet point (•) at the start
- Return points as a single string with newlines between points

Example good talking points:
• Your 'Mindful Mornings' meditation group could share experiences and support each other between sessions
• Members from Tuesday's HIIT and Thursday's Strength classes could form accountability partnerships
• Your nutrition coaching clients could share recipes and progress in private groups

Example bad talking points (too generic):
• Foster community engagement through member-only forums and events
• Enhance member retention with personalized groups
• Streamline communication with automated updates

{parser.get_format_instructions()}"""},
                    {"role": "user", "content": f"Please analyze this webpage content and create highly specific talking points that reference their actual offerings:\n{combined_text}"}
                ]
                
                # Get LLM response
                response = _llm(messages)
                if response:
                    try:
                        result = parser.parse(response)
                        
                        # Format notes as bullet points if they aren't already
                        notes = result.notes
                        if not notes.startswith('•'):
                            notes = '\n'.join(f"• {point.strip()}" for point in notes.split('\n') if point.strip())
                        
                        # Prepare the update
                        update = {
                            'Org Name': lead.get('Org Name', ''),
                            'Link': url,
                            'Phone Number': result.phone or lead.get('Phone Number', ''),
                            'Email': result.email or lead.get('Email', ''),
                            'Notes': notes,
                            'Checked?': 'checked'
                        }
                        
                        # Write update
                        write_to_leads_sheet(service, spreadsheet_id, [update], update_mode=True)
                        print(f"Updated lead: {url}")
                        
                    except Exception as e:
                        print(f"Error parsing LLM response for {url}: {e}")
                        print(f"Raw response: {response}")
            except Exception as e:
                print(f"Error processing URL {url}: {str(e)}")
                
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")
        finally:
            if 'page' in locals():
                await page.close()
            await asyncio.sleep(random.uniform(1, 2))

def write_to_leads_sheet(service, spreadsheet_id, leads, update_mode=False):
    """Write or update leads in the leads sheet"""
    # Get existing data
    existing_data = get_sheet_data(service, spreadsheet_id, 'leads!A:J')
    
    if not existing_data:
        print("No data found in leads sheet")
        return
    
    headers = existing_data[0]
    rows = [headers]  # Start with headers
    
    # Create a map of URLs to their row index
    url_index = headers.index('Link')
    url_to_index = {}
    for i, row in enumerate(existing_data[1:], 1):
        if len(row) > url_index and row[url_index]:
            url_to_index[row[url_index]] = i
    
    # Start with existing data
    rows.extend(existing_data[1:])
    
    # Update or append each lead
    for lead in leads:
        if not lead.get('Link'):
            continue
            
        new_row = [
            lead.get('Org Name', ''),
            lead.get('Link', ''),
            lead.get('Phone Number', ''),
            lead.get('Email', ''),
            lead.get('Notes', ''),
            lead.get('Blank', ''),
            lead.get('Checked?', ''),
            lead.get('Called?', ''),
            lead.get('Emailed?', ''),
            lead.get('Contacted?', '')
        ]
        
        if update_mode and lead['Link'] in url_to_index:
            # Update existing row while preserving some fields
            existing_row = rows[url_to_index[lead['Link']]]
            # Extend existing row if needed
            while len(existing_row) < len(headers):
                existing_row.append('')
            
            # Update only non-empty fields from new data
            for i, (new_val, header) in enumerate(zip(new_row, headers)):
                if new_val and header not in ['Called?', 'Emailed?', 'Contacted?']:  # Preserve these fields
                    existing_row[i] = new_val
        else:
            # Append new row
            rows.append(new_row)
            print(f"Added new lead: {lead['Link']}")
    
    # Prepare the request
    body = {
        'values': rows
    }
    
    try:
        # Update entire range
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='leads!A1',
            valueInputOption='RAW',
            body=body
        ).execute()
        
        print(f"Successfully processed {len(leads)} leads")
    except Exception as e:
        print(f"Error writing to sheet: {str(e)}")

async def process_leads(context, service, spreadsheet_id, selected_leads):
    """Process selected leads in parallel with a limit on concurrency"""
    if not selected_leads:
        print("No leads to process")
        return
    
    # Create a semaphore to limit concurrency
    max_concurrent = 5
    semaphore = asyncio.Semaphore(max_concurrent)
    
    print(f"Processing {len(selected_leads)} leads with max {max_concurrent} concurrent tasks")
    
    # Create tasks for each lead
    tasks = []
    for i, lead in enumerate(selected_leads, 1):
        task = process_single_lead(
            context, service, spreadsheet_id, 
            lead, i, len(selected_leads), semaphore
        )
        tasks.append(task)
    
    # Run tasks concurrently
    await asyncio.gather(*tasks)
    
    print("\nFinished processing all leads")

async def check_leads(selected_leads, spreadsheet_id):
    """Process selected leads to update contact information and generate notes"""
    # Connect to Google Sheets
    service = connect_to_sheets(spreadsheet_id)
    
    # Set up browser
    context, playwright = await setup_browser()
    try:
        logger.info("\nChecking leads for contact information...")
        await process_leads(context, service, spreadsheet_id, selected_leads)
        logger.info("\nFinished checking leads")
    finally:
        await context.close()
        await playwright.stop() 