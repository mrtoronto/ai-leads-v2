import os
from playwright.async_api import async_playwright


USER_DIR = os.path.expanduser('~/.playwright_profiles')


async def setup_browser():
    """Set up a browser instance with appropriate settings"""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,  # Back to headless
        args=[
            '--disable-gpu', 
            '--no-sandbox', 
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',  # Hide automation flags
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor'
        ]
    )
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',  # Updated user agent
        ignore_https_errors=True,
        # Add extra settings to avoid detection
        extra_http_headers={
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document'
        }
    )
    
    # Remove webdriver property to avoid detection
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
    """)
    
    return context, playwright