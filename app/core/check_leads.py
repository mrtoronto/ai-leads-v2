import streamlit as st
import asyncio
import random
from datetime import datetime
from app.llm.llm import _llm
from app.utils.browser import setup_browser
from app.utils.gcs import connect_to_sheets, get_sheet_data
from app.utils.sheet_cache import get_sheet_data_cached
from app.core.models import LeadCheckResult
from langchain.output_parsers import PydanticOutputParser

async def process_single_lead(context, service, spreadsheet_id, lead, i, total, semaphore):
    """Process a single lead to update contact info and generate notes"""
    url = lead.get('Link', '')
    if not url:
        print(f"Skipping lead {i}/{total} - no URL")
        return
        
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
                        response = await page.goto(url, wait_until='networkidle', timeout=15000)
                    except Exception as e:
                        if 'timeout' in str(e).lower():
                            print(f"Networkidle timeout for {page_name}, falling back to domcontentloaded...")
                            response = await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        else:
                            raise
                    
                    if response and response.status < 400:
                        # Wait a bit for dynamic content
                        await page.wait_for_timeout(2000)
                        
                        # Get page content
                        content = await page.evaluate('() => document.body.innerText')
                        page_contents[page_name] = content
                        
                        # Also get all links on the page
                        links = await page.evaluate("""() => {
                            const links = Array.from(document.querySelectorAll('a'));
                            return links.map(link => ({
                                text: link.innerText.trim(),
                                href: link.href,
                                isContact: link.href.toLowerCase().includes('contact') || 
                                         link.innerText.toLowerCase().includes('contact')
                            }));
                        }""")
                        return links
                    return []
                except Exception as e:
                    print(f"Error accessing {page_name} page: {str(e)}")
                    return []
            
            # Start with the provided URL
            base_url = url.split('/')[0] + '//' + url.split('/')[2]  # Get base domain
            links = await get_page_content(url, 'initial')
            
            # If we started on a contact page, also visit home page
            if 'contact' in url.lower():
                await get_page_content(base_url, 'home')
            
            # Look for and visit contact page if we haven't already
            contact_links = [link for link in links if link['isContact']]
            if contact_links and 'contact' not in url.lower():
                await get_page_content(contact_links[0]['href'], 'contact')
            
            # If we haven't found a contact page yet, try common contact URLs
            if 'contact' not in page_contents:
                common_contact_paths = ['/contact', '/contact-us', '/about', '/about-us']
                for path in common_contact_paths:
                    if len(page_contents) >= 3:  # Limit to 3 pages maximum
                        break
                    await get_page_content(base_url + path, f'extra_{path}')
            
            # If we got no content, try one last time with the base URL
            if not page_contents and base_url != url:
                await get_page_content(base_url, 'home')
            
            # If we still got no content, exit
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

async def check_leads(selected_leads):
    """Process selected leads to update contact information and generate notes"""
    # Connect to Google Sheets
    service = connect_to_sheets(st.session_state.spreadsheet_id)
    
    # Set up browser
    context, playwright = await setup_browser()
    try:
        print("\nChecking leads for contact information...")
        await process_leads(context, service, st.session_state.spreadsheet_id, selected_leads)
        print("\nFinished checking leads")
    finally:
        await context.close()
        await playwright.stop() 