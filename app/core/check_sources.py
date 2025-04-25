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


def normalize_url_for_comparison(url):
    """Normalize URL for comparison by removing protocol, www, and trailing slashes"""
    if not url:
        return ""
    
    # Convert to lowercase
    url = url.lower()
    
    # Remove http:// or https://
    if url.startswith("http://"):
        url = url[7:]
    elif url.startswith("https://"):
        url = url[8:]
    
    # Remove www.
    if url.startswith("www."):
        url = url[4:]
    
    # Remove trailing slash
    if url.endswith("/"):
        url = url[:-1]
    
    return url


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
        {"role": "system", "content": LEAD_SOURCE_PROMPT.render(format_instruction=parser_lead_source.get_format_instructions())},
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


async def process_single_source(context, service, spreadsheet_id, source, i, total, semaphore):
    """Process a single source and extract contact information"""
    headers = ['Title', 'URL', 'Description', 'Date Found', 'Status', 'Leads Found']
    url_index = headers.index('URL')
    status_index = headers.index('Status')
    title_index = headers.index('Title')
    desc_index = headers.index('Description')
    date_index = headers.index('Date Found')
    leads_found_index = headers.index('Leads Found')
    
    # Ensure source has all required fields
    while len(source) < len(headers):
        source.append('')
    
    url = source[url_index]
    print(f"\nProcessing: {url} ({i}/{total})")
    
    async with semaphore:  # Use semaphore to limit concurrent requests
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
                await update_all_matching_sources(service, spreadsheet_id, url)
                await page.close()
                return
            
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
                await update_all_matching_sources(service, spreadsheet_id, url)
                await page.close()
                return
            
            await asyncio.sleep(random.uniform(1, 2))
            
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
                await update_all_matching_sources(service, spreadsheet_id, url)
                print(f"Updated source and added {len(sources_to_update)-1} new sources")
            
            print(f"Found {total_leads} leads and {len(validation_result.AdditionalLeadSourcesFound if validation_result else [])} additional sources")
            
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
            await update_all_matching_sources(service, spreadsheet_id, url)
            print("Marked errored source as checked")
        finally:
            if 'page' in locals():
                await page.close()
            await asyncio.sleep(random.uniform(1, 2))  # Add a short delay between processing


async def process_sources(context, service, spreadsheet_id):
    """Process sources in parallel with a limit on concurrency"""
    # Get sources
    sources = get_sheet_data(service, spreadsheet_id, 'sources!A:F')
    if len(sources) <= 1:  # Only headers or empty
        print("No sources to process")
        return
    
    headers = sources[0]
    status_index = headers.index('Status')
    
    # Filter sources that need to be checked
    sources_to_check = [source for source in sources[1:] if source[status_index] != 'checked']
    
    if not sources_to_check:
        print("No new sources to process")
        return
    
    # Create a semaphore to limit concurrency
    # Adjust the number based on your system's capacity and API rate limits
    max_concurrent = 5
    semaphore = asyncio.Semaphore(max_concurrent)
    
    print(f"Processing {len(sources_to_check)} sources with max {max_concurrent} concurrent tasks")
    
    # Create tasks for each source
    tasks = []
    for i, source in enumerate(sources_to_check, 1):
        task = process_single_source(
            context, service, spreadsheet_id, 
            source, i, len(sources_to_check), semaphore
        )
        tasks.append(task)
    
    # Run tasks concurrently
    await asyncio.gather(*tasks)
    
    print("\nFinished processing all sources")


async def update_all_matching_sources(service, spreadsheet_id, target_url):
    """Update all sources with the same URL to be marked as checked
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: ID of the spreadsheet
        target_url: URL to find matching sources for
    """
    # Get all sources
    sources = get_sheet_data(service, spreadsheet_id, 'sources!A:F')
    if len(sources) <= 1:  # Only headers or empty
        return
    
    headers = sources[0]
    url_index = headers.index('URL')
    status_index = headers.index('Status')
    returns_index = headers.index('Returns') if 'Returns' in headers else -1
    
    # Normalize the target URL for comparison
    normalized_target = normalize_url_for_comparison(target_url)
    
    # Look for any other sources with matching URLs that aren't checked
    sources_to_update = []
    
    for i, source in enumerate(sources[1:], 1):
        # Ensure source has all required fields
        while len(source) < len(headers):
            source.append('')
        
        current_url = source[url_index]
        normalized_current = normalize_url_for_comparison(current_url)
        
        # If URLs match (after normalization) but not checked, add to update list
        if (normalized_current == normalized_target and 
            source[status_index].lower() != 'checked'):
            
            # Create copy of source with status set to checked
            updated_source = source.copy()
            updated_source[status_index] = 'checked'
            
            update_dict = {
                'title': updated_source[headers.index('Title')],
                'url': updated_source[url_index],  # Keep original URL format
                'description': updated_source[headers.index('Description')],
                'date_found': updated_source[headers.index('Date Found')],
                'status': 'checked'
            }
            
            # Handle 'Returns' column if it exists
            if returns_index >= 0 and len(updated_source) > returns_index:
                update_dict['returns'] = updated_source[returns_index]
                
            sources_to_update.append(update_dict)
    
    # Write updates if any matching sources were found
    if sources_to_update:
        write_to_sources_sheet(service, spreadsheet_id, sources_to_update)
        print(f"Updated {len(sources_to_update)} additional sources with normalized URL: {normalized_target}")


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
