import os
from playwright.async_api import async_playwright


USER_DIR = os.path.expanduser('~/.playwright_profiles')


async def setup_browser():
    """Initialize and return a playwright browser instance with stealth settings"""
    playwright = await async_playwright().start()
    
    # Ensure profile directory exists
    os.makedirs(USER_DIR, exist_ok=True)
    
    # Use persistent context with a profile
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=USER_DIR,
        headless=True,  # Always run in headless mode
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        args=[
            '--window-size=1920,1080',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=IsolateOrigins,site-per-process',
        ],
        ignore_default_args=['--enable-automation'],
        accept_downloads=True
    )
    
    # Add extra headers to appear more legitimate
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
    """)
    
    return context, playwright