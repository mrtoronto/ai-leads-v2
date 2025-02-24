import streamlit as st
import json
import asyncio
import random
from app.utils.gcs import connect_to_sheets, get_existing_urls, write_to_sources_sheet, write_to_searches_sheet
from app.utils.browser import setup_browser
from datetime import datetime
from app.llm.prompts import SEARCH_RESULTS_PROMPT, USER_BUSINESS_MESSAGE
from app.core.models import parser_lead_source_list
from app.llm.llm import _llm
CHUNK_SIZE = 25


async def validate_search_results(results, existing_urls):
    """Validate search results in chunks using GPT-4o-mini"""
    # Remove duplicates first
    unique_results = []
    seen_urls = set()
    
    for result in results:
        url = result['url']
        # Skip if URL is already in sources sheet or if we've seen it in this batch
        if url not in existing_urls and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(result)
    
    print(f"Found {len(unique_results)} unique results after deduplication")
    
    # Split unique results into chunks
    chunks = [unique_results[i:i + CHUNK_SIZE] for i in range(0, len(unique_results), CHUNK_SIZE)]
    validated_results = []
    
    for chunk in chunks:
        # Prepare the URLs with full context
        sources = [
            {
                "name": result["title"],
                "url": result["url"],
                "description": result["description"]
            } 
            for result in chunk
        ]

        messages = [
            {"role": "system", "content": SEARCH_RESULTS_PROMPT.render(format_instruction=parser_lead_source_list.get_format_instructions())},
            {"role": "user", "content": USER_BUSINESS_MESSAGE},
            {"role": "user", "content": f"Please validate these sources and return only the relevant ones:\n{json.dumps(sources, indent=2)}"}
        ]
        
        # Get LLM response
        response = _llm(messages)
        if response:
            try:
                validated_chunk = parser_lead_source_list.parse(response)
                # Add validated sources back to results
                for source in validated_chunk.RelevantSources:
                    matching_result = next((r for r in chunk if r["url"] == source.url), None)
                    if matching_result:
                        validated_results.append(matching_result)
            except Exception as e:
                print(f"Error parsing LLM response: {e}")
                print(f"Raw response: {response}")
                # If parsing fails, include the entire chunk to be safe
                validated_results.extend(chunk)
        
        # Add delay between chunks
        await asyncio.sleep(random.uniform(1, 2))
    
    return validated_results

async def collect_search_results(page):
    """Collect detailed information about search results"""
    results = []
    result_elements = await page.query_selector_all('div.g')
    
    for result in result_elements:
        try:
            # Get title
            title_elem = await result.query_selector('h3')
            title = await title_elem.inner_text() if title_elem else ''
            
            # Get URL
            link_elem = await result.query_selector('a')
            url = await link_elem.get_attribute('href') if link_elem else ''
            
            # Get description
            desc_elem = await result.query_selector('div.VwiC3b')
            description = await desc_elem.inner_text() if desc_elem else ''
            
            if title and url:  # Only add if we have at least title and URL
                results.append({
                    'title': title,
                    'url': url,
                    'description': description,
                    'date_found': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'new'
                })
        except Exception as e:
            print(f"Error collecting result: {str(e)}")
            continue
    
    return results



async def perform_google_search(context, query, service, spreadsheet_id):
    """Perform a Google search using playwright with human-like behavior"""
    page = await context.new_page()
    total_results = []
    total_pages_processed = 0
    
    async def natural_delay():
        """More natural random delay with gaussian distribution"""
        await asyncio.sleep(abs(random.gauss(2, 0.5)))
    
    try:
        # Navigate to Google with a slight delay
        await page.goto('https://www.google.com', wait_until='networkidle')
        await natural_delay()
        
        # Sometimes move mouse randomly before finding search box
        if random.random() > 0.5:
            await page.mouse.move(
                random.randint(100, 500),
                random.randint(100, 300)
            )
            await natural_delay()
        
        # Find and click search box
        search_input = await page.wait_for_selector('textarea[name="q"]')
        
        # Move to search box with natural curve
        box = await search_input.bounding_box()
        await page.mouse.move(
            box['x'] + box['width']/2 + random.randint(-10, 10),
            box['y'] + box['height']/2 + random.randint(-5, 5)
        )
        await natural_delay()
        
        await search_input.click()
        await natural_delay()
        
        # Type query with very human-like delays
        words = query.split()
        for i, word in enumerate(words):
            if i > 0:  # Add space between words
                await page.keyboard.press('Space')
                await asyncio.sleep(random.uniform(0.1, 0.3))
            
            for char in word:
                # Slower, more natural typing speed
                await page.keyboard.type(char, delay=random.uniform(150, 350))
                await asyncio.sleep(random.uniform(0.05, 0.15))
        
        await natural_delay()
        
        # Sometimes move mouse before pressing enter
        if random.random() > 0.5:
            await page.mouse.move(
                random.randint(600, 800),
                random.randint(100, 300)
            )
        
        await page.keyboard.press('Enter')
        await page.wait_for_selector('div#search', timeout=10000)
        
        # Get existing URLs before starting
        existing_urls = get_existing_urls(service, spreadsheet_id)
        
        # Process first 10 pages of results
        for page_num in range(10):
            print(f"\nProcessing page {page_num + 1} of search results...")
            await natural_delay()
            
            # Natural scrolling behavior
            for _ in range(random.randint(2, 4)):
                scroll_amount = random.randint(200, 400)
                await page.mouse.wheel(0, scroll_amount)
                await asyncio.sleep(random.uniform(1, 2))
            
            # Get search results on current page
            results = await page.query_selector_all('div.g')
            for result in results:
                title_elem = await result.query_selector('h3')
                if title_elem:
                    title = await title_elem.inner_text()
                    print(f"Found result: {title}")
            
            # Collect detailed results from current page
            page_results = await collect_search_results(page)
            print(f"Collected {len(page_results)} results from page {page_num + 1}")
            
            # Validate and write results from this page
            if page_results:
                print(f"\nValidating {len(page_results)} search results from page {page_num + 1}...")
                validated_results = await validate_search_results(page_results, existing_urls)
                if validated_results:
                    # Write results to sources sheet
                    write_to_sources_sheet(service, spreadsheet_id, validated_results)
                    # Update existing URLs with new ones
                    existing_urls.update(result['url'] for result in validated_results)
                    # Add to total results
                    total_results.extend(validated_results)
                    print(f"Added {len(validated_results)} valid results from page {page_num + 1}")
                    
                    # Update searches sheet with running total after each page
                    write_to_searches_sheet(service, spreadsheet_id, query, len(total_results))
                    print(f"Updated search record with running total: {len(total_results)} results")
            
            total_pages_processed = page_num + 1
            
            # Check if there's a next page button
            next_button = await page.query_selector('a#pnnext')
            if not next_button:
                print("No more result pages available")
                break
            
            # Add more human-like behavior before clicking next
            await natural_delay()
            
            # Move mouse to random position first
            await page.mouse.move(
                random.randint(100, 800),
                random.randint(100, 600)
            )
            await natural_delay()
            
            # Then move to and click the next button
            next_box = await next_button.bounding_box()
            await page.mouse.move(
                next_box['x'] + next_box['width']/2 + random.randint(-5, 5),
                next_box['y'] + next_box['height']/2 + random.randint(-3, 3)
            )
            await natural_delay()
            
            # Click next and wait for new results
            await next_button.click()
            await page.wait_for_selector('div#search', timeout=10000)
            
            # Add longer delay between pages to appear more human-like
            await asyncio.sleep(random.uniform(3, 5))
        
        print(f"\nCollected total of {len(total_results)} results from {total_pages_processed} pages")
        
        # Final update to searches sheet with total
        write_to_searches_sheet(service, spreadsheet_id, query, len(total_results))
        
        return page, total_results
    except Exception as e:
        print(f"Error during search: {str(e)}")
        # Even if there's an error, try to log what we found
        if total_results:
            write_to_searches_sheet(service, spreadsheet_id, query, len(total_results))
        return None, total_results



async def search_and_write(search_query):
    # Connect to Google Sheets
    service = connect_to_sheets(st.session_state.spreadsheet_id)
    
    # Set up browser and perform search
    context, playwright = await setup_browser()
    try:
        print(f"\nPerforming new search for: {search_query}")
        
        # Add random delay before starting
        await asyncio.sleep(random.uniform(2, 4))
        
        search_page, results = await perform_google_search(context, search_query, service, st.session_state.spreadsheet_id)
        
        if search_page and results:
            # Write results to sources sheet
            write_to_sources_sheet(service, st.session_state.spreadsheet_id, results)
            
            # Log the search query and number of results
            write_to_searches_sheet(service, st.session_state.spreadsheet_id, search_query, len(results))
            
            # More natural page interaction
            for _ in range(random.randint(2, 4)):
                await asyncio.sleep(random.uniform(1.5, 3))
                scroll_amount = random.randint(100, 300)
                await search_page.mouse.wheel(0, scroll_amount)
                
                if random.random() > 0.6:
                    await search_page.mouse.move(
                        random.randint(300, 1000),
                        random.randint(100, 600)
                    )
            
            # Final pause before closing
            await asyncio.sleep(random.uniform(2, 4))
            
            print("\nSearch Summary:")
            print(f"Query: {search_query}")
            print(f"Found {len(results)} relevant results")
    finally:
        await context.close()
        await playwright.stop()