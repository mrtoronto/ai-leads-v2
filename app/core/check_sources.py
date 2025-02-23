import streamlit as st
import asyncio
import random
from datetime import datetime
from app.core.models import parser_lead_source
from app.llm.llm import _llm
from app.utils.browser import setup_browser
from app.utils.gcs import get_sheet_data

from app.utils.gcs import connect_to_sheets, write_to_sources_sheet, write_to_leads_sheet
from app.llm.prompts import LEAD_SOURCE_PROMPT, USER_BUSINESS_MESSAGE


async def get_link_text_for_url(page, url):
    """Get the text of the link element that matches the given URL exactly"""
    link_text = await page.evaluate("""(targetUrl) => {
        // Find all links that match this exact URL
        const links = Array.from(document.querySelectorAll('a[href]'));
        const matchingLinks = links.filter(link => {
            try {
                // Normalize URLs for comparison
                const linkUrl = new URL(link.href);
                const targetUrlObj = new URL(targetUrl);
                return linkUrl.href === targetUrlObj.href;
            } catch {
                // If URL parsing fails, do a direct string comparison
                return link.href === targetUrl;
            }
        });
        
        if (matchingLinks.length > 0) {
            // Get text content of the first matching link
            const text = matchingLinks[0].textContent.trim();
            if (text && text.length > 1) {
                return text;
            }
            
            // If no good text in link, try to find a heading or strong text nearby
            const parent = matchingLinks[0].closest('div, section, article');
            if (parent) {
                const heading = parent.querySelector('h1, h2, h3, h4, h5, h6');
                if (heading) {
                    return heading.textContent.trim();
                }
                const strong = parent.querySelector('strong');
                if (strong) {
                    return strong.textContent.trim();
                }
            }
        }
        
        // If no good name found, try to extract from URL
        try {
            const urlObj = new URL(targetUrl);
            const domain = urlObj.hostname.replace('www.', '');
            const company = domain.split('.')[0];
            if (company.length > 3) {
                return company.split(/[-_]/).map(word => 
                    word.charAt(0).toUpperCase() + word.slice(1)
                ).join(' ');
            }
        } catch (e) {}
        
        return '';
    }""", url)
    
    # Clean up the text if we got something
    if link_text:
        # Remove extra whitespace and normalize
        link_text = ' '.join(link_text.split())
        # Remove common suffixes
        for suffix in [' - Home', ' - Contact', ' - About', ' | Home', ' | Contact']:
            if link_text.endswith(suffix):
                link_text = link_text[:-len(suffix)]
        
        # Skip if it's just navigation text
        skip_phrases = ['skip to', 'menu', 'navigation', 'search', 'logo', 'home']
        if any(phrase in link_text.lower() for phrase in skip_phrases):
            link_text = ''
    
    return link_text or 'Unknown Name'


async def process_source_with_llm(source_url, source_content):
    """Process a single source with LLM to validate and extract leads"""
    
    messages = [
        {"role": "system", "content": LEAD_SOURCE_PROMPT.render()},
        {"role": "user", "content": USER_BUSINESS_MESSAGE},
        {"role": "user", "content": f"Please analyze this webpage content and extract any relevant leads or sources:\n{source_content}"}
    ]
    
    # Get LLM response
    response = _llm(messages)
    if response:
        try:
            return parser_lead_source.parse(response)
        except Exception as e:
            print(f"Error parsing LLM response for {source_url}: {e}")
            print(f"Raw response: {response}")
    return None



async def process_sources(context, service, spreadsheet_id):
    """Process each source and extract contact information using LLM"""
    # Get sources
    sources = get_sheet_data(service, spreadsheet_id, 'sources!A:F')
    if len(sources) <= 1:  # Only headers or empty
        print("No sources to process")
        return
    
    headers = sources[0]
    url_index = headers.index('URL')
    status_index = headers.index('Status')
    title_index = headers.index('Title')
    desc_index = headers.index('Description')
    date_index = headers.index('Date Found')
    leads_found_index = len(headers) - 1
    
    # Process each source
    for i, source in enumerate(sources[1:], 1):
        # Ensure source has all required fields
        while len(source) < len(headers):
            source.append('')
        
        # Skip if already checked
        if source[status_index] == 'checked':
            continue
            
        url = source[url_index]
        print(f"\nProcessing: {url} ({i}/{len(sources)-1})")
        
        try:
            page = await context.new_page()
            response = await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Check if page load was successful
            if not response:
                print(f"Failed to load page: {url}")
                raise Exception("Page load failed")
            
            # Check response status
            status = response.status
            if status == 404:
                print(f"Page not found (404): {url}")
                error_update = [{
                    'title': source[title_index],
                    'url': url,
                    'description': f"{source[desc_index]} [404 - Page not found]",
                    'date_found': source[date_index],
                    'status': 'checked',
                    'leads_found': '0'
                }]
                write_to_sources_sheet(service, spreadsheet_id, error_update)
                await page.close()
                continue
            
            if status >= 400:
                print(f"Error loading page (HTTP {status}): {url}")
                error_update = [{
                    'title': source[title_index],
                    'url': url,
                    'description': f"{source[desc_index]} [HTTP {status}]",
                    'date_found': source[date_index],
                    'status': 'checked',
                    'leads_found': '0'
                }]
                write_to_sources_sheet(service, spreadsheet_id, error_update)
                await page.close()
                continue
            
            await asyncio.sleep(random.uniform(2, 3))
            
            # Get page title from head section
            page_title = await page.evaluate("""() => {
                const titleElement = document.querySelector('head title');
                if (titleElement) {
                    let title = titleElement.textContent.trim();
                    // Clean up common title suffixes
                    const suffixes = [' - Home', ' | Home', ' - Contact', ' | Contact', ' - About', ' | About'];
                    for (const suffix of suffixes) {
                        if (title.endsWith(suffix)) {
                            title = title.slice(0, -suffix.length).trim();
                        }
                    }
                    return title;
                }
                return null;
            }""")
            
            # Update source with page title immediately if we found one
            if page_title:
                source_update = [{
                    'title': page_title,
                    'url': url,
                    'description': source[desc_index],
                    'date_found': source[date_index],
                    'status': source[status_index],
                    'leads_found': source[leads_found_index] if len(source) > leads_found_index else '0'
                }]
                write_to_sources_sheet(service, spreadsheet_id, source_update)
                print(f"Updated source title to: {page_title}")
                # Update the source array with new title for use below
                source[title_index] = page_title
            
            # Get page content
            content = await page.content()
            visible_text = await page.evaluate('() => document.body.innerText')
            
            # Process with LLM
            validation_result = await process_source_with_llm(url, visible_text)
            
            new_leads = []
            sources_to_update = []
            
            if validation_result:
                # Add any leads found
                for lead in validation_result.LeadsFound:
                    if not lead.url:  # Skip leads without URLs
                        continue
                    
                    # Get the link text for this URL
                    lead_name = await get_link_text_for_url(page, lead.url)
                    if not lead_name:  # If no exact match, try to find similar URL
                        lead_name = await page.evaluate("""(targetUrl) => {
                            const links = Array.from(document.querySelectorAll('a'));
                            for (const link of links) {
                                if (link.href.includes(targetUrl) || targetUrl.includes(link.href)) {
                                    return link.textContent.trim();
                                }
                            }
                            return '';
                        }""", lead.url)
                    
                    new_leads.append({
                        'url': lead.url,
                        'phone': lead.phone,
                        'email': lead.email,
                        'name': lead_name or source[title_index] or 'Unknown Name'  # Use link text, source title, or default
                    })
                
                # Add any additional sources found
                for new_source in validation_result.AdditionalLeadSourcesFound:
                    if not new_source.url:  # Skip sources without URLs
                        continue
                    
                    # Get the link text for this source
                    source_name = await get_link_text_for_url(page, new_source.url) or new_source.name
                    sources_to_update.append({
                        'title': source_name,
                        'url': new_source.url,
                        'description': new_source.description,
                        'date_found': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'status': 'new',
                        'leads_found': str(len(new_source.leads_found))
                    })
                
                total_leads = len(validation_result.LeadsFound)
            else:
                total_leads = 0
            
            # Update current source status
            sources_to_update.append({
                'title': source[title_index],  # Use the already updated title
                'url': url,
                'description': source[desc_index],
                'date_found': source[date_index],
                'status': 'checked',
                'leads_found': str(total_leads)
            })
            
            # Write updates immediately after processing each source
            if new_leads:
                write_to_leads_sheet(service, spreadsheet_id, new_leads)
                print(f"Added {len(new_leads)} new leads from this source (before deduplication)")
            
            if sources_to_update:
                write_to_sources_sheet(service, spreadsheet_id, sources_to_update)
                print(f"Updated source and added {len(sources_to_update)-1} new sources")
            
            print(f"Found {total_leads} leads and {len(validation_result.AdditionalLeadSourcesFound if validation_result else [])} additional sources")
            
            await page.close()
            await asyncio.sleep(random.uniform(2, 3))
            
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")
            # Even on error, mark as checked to avoid infinite retries
            error_update = [{
                'title': source[title_index],
                'url': url,
                'description': f"{source[desc_index]} [Error: {str(e)}]",
                'date_found': source[date_index],
                'status': 'checked',
                'leads_found': '0'
            }]
            write_to_sources_sheet(service, spreadsheet_id, error_update)
            print("Marked errored source as checked")
            if 'page' in locals():
                await page.close()
            continue
    
    print("\nFinished processing all sources")


async def check_sources():
    """Process all sources in the sources sheet to find contact information"""
    # Connect to Google Sheets
    service = connect_to_sheets(st.session_state.spreadsheet_id)
    
    # Set up browser
    context, playwright = await setup_browser()
    try:
        print("\nChecking sources for contact information...")
        await process_sources(context, service, st.session_state.spreadsheet_id)
        print("\nFinished checking sources")
    finally:
        await context.close()
        await playwright.stop()
