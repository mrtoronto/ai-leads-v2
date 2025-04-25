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
import time  # Add this import if not already present
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
    
    try:
        # Wait for and get the main search results container
        await page.wait_for_selector('#search', timeout=10000)
        
        # Debug: Print page content to see what we're dealing with
        print("Analyzing search results structure...")
        
        # Try to find visible search results with more specific selectors
        result_elements = []
        selectors = [
            'div#search div.g:not([aria-hidden="true"])',  # Main results, not hidden
            'div[data-hveid]:not([aria-hidden="true"])',   # Modern results, not hidden
            'div.MjjYud',  # Common container for modern results
            'div[data-sokoban-container]'  # Another modern results container
        ]
        
        for selector in selectors:
            print(f"Trying selector: {selector}")
            elements = await page.query_selector_all(selector)
            if elements:
                # Verify elements are actually visible
                visible_elements = []
                for element in elements:
                    try:
                        is_visible = await element.is_visible()
                        if is_visible:
                            visible_elements.append(element)
                    except Exception:
                        continue
                
                if visible_elements:
                    print(f"Found {len(visible_elements)} visible results using selector: {selector}")
                    result_elements = visible_elements
                    break
                else:
                    print(f"Found {len(elements)} elements but none are visible for selector: {selector}")
        
        if not result_elements:
            print("Warning: No visible results found with any selector")
            # Debug: Print the page HTML to understand the structure
            html = await page.content()
            print("Page HTML structure:")
            print(html[:1000])  # Print first 1000 chars to see structure
            return results
            
        for result in result_elements:
            try:
                # Debug: Print the HTML of each result element
                result_html = await result.evaluate('el => el.outerHTML')
                print(f"\nProcessing result HTML:\n{result_html[:200]}...")  # First 200 chars
                
                # Get title - try multiple possible selectors
                title = ''
                title_selectors = [
                    'h3:not([aria-hidden="true"])',
                    '[role="heading"]:not([aria-hidden="true"])',
                    'h3.r',
                    'div[role="heading"]'
                ]
                for title_selector in title_selectors:
                    title_elem = await result.query_selector(title_selector)
                    if title_elem and await title_elem.is_visible():
                        title = await title_elem.inner_text()
                        if title:
                            break
                
                # Get URL - try multiple possible selectors
                url = ''
                link_selectors = [
                    'a[ping]:not([aria-hidden="true"])',
                    'a[href]:not([aria-hidden="true"])',
                    'cite'  # Sometimes URLs are in cite elements
                ]
                for link_selector in link_selectors:
                    link_elem = await result.query_selector(link_selector)
                    if link_elem and await link_elem.is_visible():
                        url = await link_elem.get_attribute('href')
                        if url:
                            # Filter out Google's internal URLs and search results
                            if url.startswith('/search') or 'google.com/search' in url:
                                continue
                            # Also try to get the actual URL from the ping attribute if it exists
                            ping_url = await link_elem.get_attribute('ping')
                            if ping_url:
                                # Extract the actual URL from the ping attribute
                                try:
                                    actual_url = ping_url.split('&url=')[1].split('&')[0]
                                    if actual_url:
                                        url = actual_url
                                except:
                                    pass
                            break
                
                # Get description - try multiple possible selectors
                description = ''
                desc_selectors = [
                    'div.VwiC3b:not([aria-hidden="true"])', 
                    'div[data-content-feature="1"]:not([aria-hidden="true"])',
                    'div[style*="webkit-line-clamp"]',  # Modern snippet style
                    'div.s'
                ]
                for desc_selector in desc_selectors:
                    desc_elem = await result.query_selector(desc_selector)
                    if desc_elem and await desc_elem.is_visible():
                        description = await desc_elem.inner_text()
                        if description:
                            break
                
                if title and url and not url.startswith('/search'):  # Only add if we have valid title and external URL
                    print(f"Found result: {title} ({url})")
                    results.append({
                        'title': title,
                        'url': url,
                        'description': description,
                        'date_found': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'status': 'new'
                    })
            except Exception as e:
                print(f"Error processing individual result: {str(e)}")
                continue
        
        print(f"Successfully collected {len(results)} results")
        return results
        
    except Exception as e:
        print(f"Error in collect_search_results: {str(e)}")
        print("Full error:", str(e))
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

        # Handle location popup if it appears
        try:
            # Look for the g-raised-button containing "Not now" text
            not_now_button = await page.wait_for_selector('g-raised-button:has-text("Not now")', timeout=5000)
            if not_now_button:
                await not_now_button.click()
                await natural_delay()
        except Exception:
            # If no popup or click fails, continue normally
            pass
        
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
            
            # Scroll to bottom to ensure next button is in view
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await natural_delay()
            
            # Try multiple selectors for the next button
            next_button = None
            next_button_selectors = [
                'a#pnnext',  # Traditional next button
                'span:has-text("Next")',  # Text-based next button
                '[aria-label="Next page"]',  # Accessibility next button
                'g-raised-button:has-text("Next")'  # Modern next button
            ]
            
            for selector in next_button_selectors:
                try:
                    button = await page.wait_for_selector(selector, timeout=5000)
                    if button and await button.is_visible():
                        next_button = button
                        print(f"Found next button using selector: {selector}")
                        break
                except Exception:
                    continue
            
            if not next_button:
                print("No more result pages available")
                break
            
            # Add more human-like behavior before clicking next
            await natural_delay()
            
            # Ensure button is in view
            await next_button.scroll_into_view_if_needed()
            await natural_delay()
            
            # Move mouse to random position first
            await page.mouse.move(
                random.randint(100, 800),
                random.randint(100, 600)
            )
            await natural_delay()
            
            # Then move to and click the next button
            next_box = await next_button.bounding_box()
            if next_box:
                await page.mouse.move(
                    next_box['x'] + next_box['width']/2 + random.randint(-5, 5),
                    next_box['y'] + next_box['height']/2 + random.randint(-3, 3)
                )
                await natural_delay()
                
                # Click and wait for new results
                await next_button.click()
                await page.wait_for_selector('div#search', timeout=10000)
                
                # Add longer delay between pages to appear more human-like
                await asyncio.sleep(random.uniform(3, 5))
            else:
                print("Next button not clickable, ending search")
                break
        
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
    # Start timing
    start_time = time.time()
    
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
            
            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            print(f"Search completed in {elapsed_time:.2f} seconds")
            
            # Return search results and timing info
            return len(results), elapsed_time
        
        # Return zeros if no results were found
        return 0, time.time() - start_time
    finally:
        await context.close()
        await playwright.stop()

async def run_multiple_searches(search_queries):
    """Run multiple search queries sequentially"""
    # Start timing the entire batch
    batch_start_time = time.time()
    
    # Track results for each query
    search_results = []
    
    # Connect to Google Sheets
    service = connect_to_sheets(st.session_state.spreadsheet_id)
    
    for i, query in enumerate(search_queries, 1):
        print(f"\n{'='*50}")
        print(f"Starting search {i} of {len(search_queries)}: {query}")
        print(f"{'='*50}\n")
        
        # Start timing this query
        query_start_time = time.time()
        
        # Add random delay between searches
        delay = random.uniform(10, 15)  # Increased delay between searches
        print(f"Waiting {delay:.2f} seconds before starting next search...")
        await asyncio.sleep(delay)
        
        context = None
        playwright = None
        search_page = None
        
        try:
            print("Setting up new browser session...")
            context, playwright = await setup_browser()
            print("Browser session created successfully")
            
            search_page, results = await perform_google_search(context, query, service, st.session_state.spreadsheet_id)
            
            # Calculate query elapsed time
            query_elapsed_time = time.time() - query_start_time
            
            if search_page and results:
                print(f"\nSearch completed successfully:")
                print(f"- Query: {query}")
                print(f"- Results found: {len(results)}")
                print(f"- Time taken: {query_elapsed_time:.2f} seconds")
                
                search_results.append({
                    "query": query,
                    "results_count": len(results),
                    "time_taken": query_elapsed_time
                })
            else:
                print(f"\nSearch completed but no results found for: {query}")
                search_results.append({
                    "query": query,
                    "results_count": 0,
                    "time_taken": query_elapsed_time
                })
                
        except Exception as e:
            print(f"\nError during search for query '{query}':")
            print(f"Error details: {str(e)}")
            search_results.append({
                "query": query,
                "results_count": 0,
                "time_taken": time.time() - query_start_time,
                "error": str(e)
            })
            
        finally:
            print("\nCleaning up resources...")
            
            # Close the search page if it exists
            if search_page:
                try:
                    print("Closing search page...")
                    await search_page.close()
                    print("Search page closed successfully")
                except Exception as e:
                    print(f"Error closing search page: {str(e)}")
            
            # Close the context if it exists
            if context:
                try:
                    print("Closing browser context...")
                    await context.close()
                    print("Browser context closed successfully")
                except Exception as e:
                    print(f"Error closing browser context: {str(e)}")
            
            # Stop playwright if it exists
            if playwright:
                try:
                    print("Stopping playwright...")
                    await playwright.stop()
                    print("Playwright stopped successfully")
                except Exception as e:
                    print(f"Error stopping playwright: {str(e)}")
            
            print("Cleanup completed")
            
            # Add extra delay after cleanup
            delay = random.uniform(15, 20)  # Increased post-search delay
            print(f"Waiting {delay:.2f} seconds before next search...")
            await asyncio.sleep(delay)
    
    # Calculate total elapsed time
    total_elapsed_time = time.time() - batch_start_time
    total_results = sum(item["results_count"] for item in search_results)
    
    print(f"\n{'='*50}")
    print("Batch Summary:")
    print(f"- Total searches completed: {len(search_queries)}")
    print(f"- Total results found: {total_results}")
    print(f"- Total time taken: {total_elapsed_time:.2f} seconds")
    print(f"{'='*50}\n")
    
    # Return the results summary
    return {
        "queries": search_results,
        "total_time": total_elapsed_time,
        "total_results": total_results
    }