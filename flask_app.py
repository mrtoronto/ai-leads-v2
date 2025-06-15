from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import asyncio
import logging
from datetime import datetime

# Core functionality imports
from app.core.check_sources import check_sources
from app.core.expand_search import expand_searches
from app.core.run_search import search_and_write, run_multiple_searches
from app.core.check_leads import check_leads
from app.core.create_gmail_drafts import create_multiple_gmail_drafts
from app.core.create_zoho_drafts import (
    normalize_url,
    update_lead_emailed_status,
    check_if_already_emailed
)

# Utility imports
from app.utils.gcs import (
    connect_to_sheets, 
    create_new_spreadsheet,
    get_spreadsheet_metadata
)
from app.utils.cache import get_spreadsheet_id_from_cache, save_spreadsheet_id_to_cache
from app.utils.template_cache import save_templates_to_cache, load_templates_from_cache
from app.utils.sheet_cache import (
    get_sheet_data_cached, 
    update_cache_after_write, 
    clear_cache, 
    get_cache_info,
    load_all_sheets
)

# Configuration imports
from app.llm.email_template import EMAIL_TEMPLATES, DEFAULT_EMAIL_TEMPLATES, ZAKAYA_CONTEXT, DEFAULT_ZAKAYA_CONTEXT
from app.llm.llm import _llm
from app.local_settings import (
    GMAIL_USER_EMAIL,
    firestore_creds
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'dev-secret-key-change-in-production'

# Helper function to run async operations
def run_async(coro):
    """Run an async coroutine in a sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# Initialize session data
def init_session():
    if 'spreadsheet_id' not in session:
        cached_id = get_spreadsheet_id_from_cache()
        session['spreadsheet_id'] = cached_id if cached_id else ""
    if 'current_templates' not in session:
        session['current_templates'] = EMAIL_TEMPLATES.copy()
    if 'context' not in session:
        session['context'] = ZAKAYA_CONTEXT

@app.before_request
def before_request():
    init_session()

@app.route('/')
def index():
    """Main page with navigation"""
    sheet_info = None
    cache_info = get_cache_info()
    
    if session.get('spreadsheet_id'):
        try:
            service = connect_to_sheets(session['spreadsheet_id'])
            sheet_info = get_spreadsheet_metadata(service, session['spreadsheet_id'])
            
            # Load sheets into cache if not initialized
            if not cache_info['initialized']:
                load_all_sheets(service, session['spreadsheet_id'])
                cache_info = get_cache_info()
        except Exception as e:
            logger.error(f"Error loading sheet info: {e}")
    
    return render_template('index.html', 
                         sheet_info=sheet_info,
                         cache_info=cache_info,
                         spreadsheet_id=session.get('spreadsheet_id', ''))

@app.route('/update_spreadsheet', methods=['POST'])
def update_spreadsheet():
    """Update the spreadsheet ID"""
    data = request.get_json()
    new_id = data.get('spreadsheet_id', '')
    
    if new_id != session.get('spreadsheet_id'):
        clear_cache()
        session['spreadsheet_id'] = new_id
        save_spreadsheet_id_to_cache(new_id)
    
    return jsonify({'success': True})

@app.route('/refresh_cache', methods=['POST'])
def refresh_cache():
    """Refresh the sheet cache"""
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/create_sheet')
def create_sheet():
    """Create new sheet page"""
    return render_template('create_sheet.html')

@app.route('/create_sheet', methods=['POST'])
def create_sheet_post():
    """Handle sheet creation"""
    data = request.get_json()
    title = data.get('title')
    email = data.get('email')
    
    if not title or not email:
        return jsonify({'success': False, 'error': 'Title and email are required'})
    
    try:
        service = connect_to_sheets(session.get('spreadsheet_id', ''))
        new_id = create_new_spreadsheet(service, title, email)
        
        if new_id:
            session['spreadsheet_id'] = new_id
            save_spreadsheet_id_to_cache(new_id)
            return jsonify({
                'success': True, 
                'spreadsheet_id': new_id,
                'url': f'https://docs.google.com/spreadsheets/d/{new_id}'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to create spreadsheet'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/generate_searches')
def generate_searches():
    """Generate searches page"""
    searches_data = []
    stats = {'total': 0, 'new': 0, 'completed': 0}
    
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            df = get_sheet_data_cached(service, session['spreadsheet_id'], 'searches')
            
            if df is not None and not df.empty:
                searches_data = df.to_dict('records')
                stats['total'] = len(df)
                stats['new'] = len(df[df['Returns'].fillna('').str.lower() == 'new'])
                stats['completed'] = stats['total'] - stats['new']
    except Exception as e:
        logger.error(f"Error loading searches: {e}")
    
    return render_template('generate_searches.html', 
                         searches=searches_data,
                         stats=stats)

@app.route('/generate_searches', methods=['POST'])
def generate_searches_post():
    """Handle search generation"""
    data = request.get_json()
    additional_context = data.get('context', '')
    
    try:
        spreadsheet_id = session.get('spreadsheet_id')
        if not spreadsheet_id:
            return jsonify({'success': False, 'error': 'No spreadsheet ID found in session'})
            
        run_async(expand_searches(spreadsheet_id, additional_context))
        
        # Refresh cache
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/run_search')
def run_search():
    """Run search page"""
    searches_data = []
    
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            df = get_sheet_data_cached(service, session['spreadsheet_id'], 'searches')
            
            if df is not None and not df.empty:
                searches_data = df.to_dict('records')
    except Exception as e:
        logger.error(f"Error loading searches: {e}")
    
    return render_template('run_search.html', searches=searches_data)

@app.route('/run_search', methods=['POST'])
def run_search_post():
    """Handle search execution"""
    data = request.get_json()
    search_type = data.get('type', 'single')
    
    try:
        spreadsheet_id = session.get('spreadsheet_id')
        if not spreadsheet_id:
            return jsonify({'success': False, 'error': 'No spreadsheet ID found in session'})
        
        if search_type == 'single':
            query = data.get('query')
            if not query:
                return jsonify({'success': False, 'error': 'Query is required'})
            
            results_count, elapsed_time = run_async(search_and_write(query, spreadsheet_id))
            
            # Refresh cache
            if session.get('spreadsheet_id'):
                service = connect_to_sheets(session['spreadsheet_id'])
                load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
            
            return jsonify({
                'success': True,
                'results_count': results_count,
                'elapsed_time': elapsed_time
            })
        
        elif search_type == 'multiple':
            queries = data.get('queries', [])
            if not queries:
                return jsonify({'success': False, 'error': 'No queries selected'})
            
            results = run_async(run_multiple_searches(queries, spreadsheet_id))
            
            # Refresh cache
            if session.get('spreadsheet_id'):
                service = connect_to_sheets(session['spreadsheet_id'])
                load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
            
            return jsonify({
                'success': True,
                'results': results
            })
    
    except Exception as e:
        logger.error(f"Error in run_search_post: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_sources')
def check_sources_page():
    """Check sources page"""
    sources_data = []
    stats = {'total': 0, 'checked': 0, 'new': 0}
    
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            df = get_sheet_data_cached(service, session['spreadsheet_id'], 'sources')
            
            if df is not None and not df.empty:
                sources_data = df.to_dict('records')
                stats['total'] = len(df)
                stats['checked'] = len(df[df['Status'] == 'checked'])
                stats['new'] = len(df[df['Status'] == 'new'])
    except Exception as e:
        logger.error(f"Error loading sources: {e}")
    
    return render_template('check_sources.html', 
                         sources=sources_data,
                         stats=stats)

@app.route('/check_sources', methods=['POST'])
def check_sources_post():
    """Handle source checking"""
    try:
        spreadsheet_id = session.get('spreadsheet_id')
        if not spreadsheet_id:
            return jsonify({'success': False, 'error': 'No spreadsheet ID in session'})
        run_async(check_sources(spreadsheet_id))
        # Refresh cache
        service = connect_to_sheets(spreadsheet_id)
        load_all_sheets(service, spreadsheet_id, force_refresh=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_leads')
def check_leads_page():
    """Check leads page"""
    leads_data = []
    stats = {'available': 0, 'checked': 0}
    
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            df = get_sheet_data_cached(service, session['spreadsheet_id'], 'leads')
            
            if df is not None and not df.empty:
                # Filter unchecked leads
                unchecked = df[df['Checked?'].fillna('').str.lower() != 'checked']
                leads_data = unchecked.to_dict('records')
                stats['available'] = len(unchecked)
                stats['checked'] = len(df) - len(unchecked)
    except Exception as e:
        logger.error(f"Error loading leads: {e}")
    
    return render_template('check_leads.html', 
                         leads=leads_data,
                         stats=stats)

@app.route('/check_leads', methods=['POST'])
def check_leads_post():
    """Handle lead checking"""
    data = request.get_json()
    selected_leads = data.get('leads', [])
    
    if not selected_leads:
        return jsonify({'success': False, 'error': 'No leads selected'})
    
    try:
        run_async(check_leads(selected_leads))
        
        # Refresh cache
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
        
        return jsonify({'success': True, 'count': len(selected_leads)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/send_emails')
def send_emails():
    """Send emails page"""
    leads_data = []
    stats = {'available': 0, 'emailed': 0}
    
    try:
        if session.get('spreadsheet_id'):
            service = connect_to_sheets(session['spreadsheet_id'])
            df = get_sheet_data_cached(service, session['spreadsheet_id'], 'leads')
            
            if df is not None and not df.empty:
                # Filter leads with emails that haven't been emailed
                with_email = df[df['Email'].notna() & (df['Email'].str.strip() != '') & (df['Link'].str.strip() != '')]
                if 'Emailed?' in df.columns:
                    not_emailed = with_email[with_email['Emailed?'].fillna('').str.lower() == '']
                else:
                    not_emailed = with_email
                
                leads_data = not_emailed.to_dict('records')
                stats['available'] = len(not_emailed)
                stats['emailed'] = len(with_email) - len(not_emailed)
    except Exception as e:
        logger.error(f"Error loading leads: {e}")
    
    return render_template('send_emails.html', 
                         leads=leads_data,
                         stats=stats,
                         gmail_user=GMAIL_USER_EMAIL)

@app.route('/send_emails', methods=['POST'])
def send_emails_post():
    """Handle email sending via Gmail"""
    try:
        data = request.get_json()
        selected_leads = data.get('selected_leads', [])
        gmail_user = data.get('gmail_user', GMAIL_USER_EMAIL)
        from_email = data.get('from_email', gmail_user)
        
        if not selected_leads:
            return jsonify({'success': False, 'error': 'No leads selected'})
        
        # Prepare contacts in the format expected by Gmail function: (website, email, notes)
        contacts = []
        for lead in selected_leads:
            contacts.append((
                normalize_url(lead.get('Link', '')),
                lead.get('Email', ''),
                lead.get('Notes', '')
            ))
        
        create_multiple_gmail_drafts(
            service_account_info=firestore_creds,
            user_email=gmail_user,
            contacts=contacts,
            from_email=from_email,
            spreadsheet_id=session['spreadsheet_id']
        )
        
        # Refresh cache after processing
        service = connect_to_sheets(session['spreadsheet_id'])
        load_all_sheets(service, session['spreadsheet_id'], force_refresh=True)
        
        return jsonify({'success': True, 'count': len(contacts)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/configure_templates')
def configure_templates():
    """Configure templates page"""
    return render_template('configure_templates.html',
                         templates=session.get('current_templates', EMAIL_TEMPLATES),
                         context=session.get('context', ZAKAYA_CONTEXT))

@app.route('/update_template', methods=['POST'])
def update_template():
    """Update a specific template"""
    data = request.get_json()
    template_type = data.get('template_type')
    
    if not template_type or template_type not in session['current_templates']:
        return jsonify({'success': False, 'error': 'Invalid template type'})
    
    # Update template
    session['current_templates'][template_type] = {
        'subject': data.get('subject', ''),
        'main_pitch': data.get('main_pitch', ''),
        'extra_context': data.get('extra_context', '')
    }
    
    # Save to cache
    cache_data = session['current_templates'].copy()
    cache_data['context'] = session.get('context', ZAKAYA_CONTEXT)
    save_templates_to_cache(cache_data)
    
    return jsonify({'success': True})

@app.route('/update_context', methods=['POST'])
def update_context():
    """Update business context"""
    data = request.get_json()
    context = data.get('context', '')
    
    session['context'] = context
    
    # Save to cache
    cache_data = session['current_templates'].copy()
    cache_data['context'] = context
    save_templates_to_cache(cache_data)
    
    return jsonify({'success': True})

@app.route('/improve_context', methods=['POST'])
def improve_context():
    """Use AI to improve business context"""
    data = request.get_json()
    improvement_input = data.get('improvement_input', '')
    
    if not improvement_input:
        return jsonify({'success': False, 'error': 'Please describe what to improve'})
    
    try:
        messages = [
            {
                "role": "system", 
                "content": """You are an expert in business communication and marketing. 
                Your task is to improve a business context that will be used as a reference by an AI that generates personalized email outreach.
                Create a well-structured, persuasive, and clear business context that highlights the key value propositions and benefits.
                Format the output as a numbered list of 5-10 points, each focused on a distinct benefit or feature.
                Keep each point under 3 sentences for clarity."""
            },
            {
                "role": "user",
                "content": f"""
                Here is the current business context:
                
                {session.get('context', ZAKAYA_CONTEXT)}
                
                The user would like to improve this context:
                
                {improvement_input}
                
                Please provide an improved context that maintains the same structure (numbered list) but incorporates the user's feedback.
                """
            }
        ]
        
        improved_context = _llm(messages)
        
        if improved_context:
            session['context'] = improved_context
            
            # Save to cache
            cache_data = session['current_templates'].copy()
            cache_data['context'] = improved_context
            save_templates_to_cache(cache_data)
            
            return jsonify({'success': True, 'context': improved_context})
        else:
            return jsonify({'success': False, 'error': 'Failed to generate improved context'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/reset_templates', methods=['POST'])
def reset_templates():
    """Reset all templates to default"""
    reset_data = DEFAULT_EMAIL_TEMPLATES.copy()
    reset_data['context'] = DEFAULT_ZAKAYA_CONTEXT
    
    save_templates_to_cache(reset_data)
    session['current_templates'] = DEFAULT_EMAIL_TEMPLATES.copy()
    session['context'] = DEFAULT_ZAKAYA_CONTEXT
    
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, port=8501)