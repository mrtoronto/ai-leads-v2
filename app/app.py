import streamlit as st
import pandas as pd

import asyncio
from app.core.check_sources import check_sources
from app.core.expand_search import expand_searches
from app.core.run_search import search_and_write
from app.core.create_zoho_drafts import (
    create_multiple_drafts, 
    ZOHO_MAIL_CLIENT_ID, 
    ZOHO_MAIL_CLIENT_SECRET, 
    ZOHO_MAIL_REFRESH_TOKEN,
    normalize_url
)
from app.utils.gcs import (
    connect_to_sheets, 
    create_new_spreadsheet,
    get_spreadsheet_metadata
)
from app.utils.cache import get_spreadsheet_id_from_cache, save_spreadsheet_id_to_cache
from app.utils.template_cache import save_templates_to_cache
from app.llm.email_template import EMAIL_TEMPLATES, DEFAULT_EMAIL_TEMPLATES, ZAKAYA_CONTEXT, DEFAULT_ZAKAYA_CONTEXT
from app.llm.llm import _llm

def get_searches_table(show_only_new=False):
    """Helper function to display searches table"""
    try:
        service = connect_to_sheets(st.session_state.spreadsheet_id)
        searches = service.spreadsheets().values().get(
            spreadsheetId=st.session_state.spreadsheet_id,
            range='searches!A:C'
        ).execute().get('values', [])
        
        if len(searches) > 1:  # If we have data beyond headers
            headers = searches[0]
            data = searches[1:]
            
            # Create DataFrame first for easier filtering
            df = pd.DataFrame(data, columns=headers)
            
            # Filter based on show_only_new flag - show completed by default
            if not show_only_new:  # When checkbox is unchecked, show completed searches
                df = df[df['Returns'].fillna('').str.lower() != 'new']
                if len(df) == 0:
                    st.info("No completed searches found.")
                    return
            else:  # When checkbox is checked, show new searches
                df = df[df['Returns'].fillna('').str.lower() == 'new']
                if len(df) == 0:
                    st.info("No new searches found.")
                    return
            
            # Display the DataFrame
            st.dataframe(
                df,
                hide_index=True
            )
        else:
            st.info("No search history found.")
    except Exception as e:
        st.error(f"Error loading search history: {str(e)}")

def get_source_stats():
    """Helper function to calculate source statistics"""
    try:
        service = connect_to_sheets(st.session_state.spreadsheet_id)
        sources = service.spreadsheets().values().get(
            spreadsheetId=st.session_state.spreadsheet_id,
            range='sources!A:F'
        ).execute().get('values', [])
        
        if len(sources) > 1:  # If we have data beyond headers
            data = sources[1:]  # Skip headers
            total_sources = len(data)
            checked_sources = sum(1 for row in data if len(row) > 4 and row[4] == 'checked')
            new_sources = sum(1 for row in data if len(row) > 4 and row[4] == 'new')
            
            return {
                "total": total_sources,
                "checked": checked_sources,
                "new": new_sources
            }
        return {"total": 0, "checked": 0, "new": 0}
    except Exception as e:
        st.error(f"Error calculating source statistics: {str(e)}")
        return {"total": 0, "checked": 0, "new": 0}
    


def app():

    # Set page config
    st.set_page_config(
        page_title="Lead Generation Tool",
        page_icon="🎯",
        layout="wide"
    )

    # Initialize session state for spreadsheet ID
    if 'spreadsheet_id' not in st.session_state:
        # Try to get ID from cache first
        cached_id = get_spreadsheet_id_from_cache()
        st.session_state.spreadsheet_id = cached_id if cached_id else ""

    # Sidebar for navigation and configuration
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select a Page",
        ["Create New Sheet", "Generate Searches", "Run Search", "Check Sources", "Send Emails", "Configure Templates"]
    )

    # Spreadsheet ID configuration
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Configuration")

    # Show current spreadsheet info
    try:
        if st.session_state.spreadsheet_id:  # Only try to connect if we have an ID
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            sheet_info = get_spreadsheet_metadata(service, st.session_state.spreadsheet_id)
            if sheet_info:
                st.sidebar.markdown(f"**Current Sheet:** [{sheet_info['title']}]({sheet_info['url']})")
    except Exception:
        st.sidebar.warning("Unable to fetch sheet information")

    new_spreadsheet_id = st.sidebar.text_input(
        "Google Sheet ID",
        value=st.session_state.spreadsheet_id,
        help="The ID of the Google Sheet to use (from the URL)"
    )

    # Update spreadsheet ID if changed
    if new_spreadsheet_id != st.session_state.spreadsheet_id:
        st.session_state.spreadsheet_id = new_spreadsheet_id
        save_spreadsheet_id_to_cache(new_spreadsheet_id)  # Save to cache when updated
        st.rerun()

    # Initialize session state for async operations
    if 'running' not in st.session_state:
        st.session_state.running = False

    def run_async_operation(operation, *args):
        """Helper function to run async operations"""
        if not st.session_state.running:
            st.session_state.running = True
            asyncio.run(operation(*args))
            st.session_state.running = False
            st.rerun()

    # New Search Page
    if page == "Run Search":
        st.title("🔍 Run Search")
        st.write("Enter a search query to find potential leads.")
        
        # Display search history first
        st.subheader("Previous Searches")
        show_new_only = st.checkbox("Show only new searches", value=True)
        get_searches_table(show_new_only)
        
        # Add some space between the table and the search input
        st.markdown("---")
        
        search_query = st.text_input(
            "Search Query",
            placeholder="e.g., Co-working spaces in California doing community events"
        )
        
        if st.button("Run Search", type="primary"):
            if search_query:
                with st.spinner("Running search..."):
                    run_async_operation(search_and_write, search_query)
                st.success("Search completed!")
            else:
                st.warning("Please enter a search query.")

    # Check Sources Page
    elif page == "Check Sources":
        st.title("📋 Check Existing Sources")
        st.write("Process all sources in the sheet to find contact information.")
        
        # Display source statistics
        stats = get_source_stats()
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Sources", stats["total"])
        with col2:
            st.metric("Checked Sources", stats["checked"])
        with col3:
            st.metric("New Sources", stats["new"])
        
        # Add some space after the metrics
        st.markdown("---")
        
        if st.button("Check Sources", type="primary"):
            with st.spinner("Checking sources for contact information..."):
                run_async_operation(check_sources)
            st.success("Source check completed!")
        
        # Display current sources
        st.subheader("Current Sources")
        try:
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            sources = service.spreadsheets().values().get(
                spreadsheetId=st.session_state.spreadsheet_id,
                range='sources!A:F'
            ).execute().get('values', [])
            
            if len(sources) > 1:  # If we have data beyond headers
                headers = sources[0]
                data = sources[1:]
                st.dataframe(
                    data,
                    column_config={
                        1: "Title",
                        2: "URL",
                        3: "Description",
                        4: "Date Found",
                        5: "Status",
                        6: "Leads Found"
                    },
                    hide_index=True
                )
            else:
                st.info("No sources found in the sheet.")
        except Exception as e:
            st.error(f"Error loading sources: {str(e)}")

    # Expand Searches Page
    elif page == "Generate Searches":
        st.title("🔄 Generate Searches")
        st.write("Generate search queries based on search history.")
        
        # Add text area for additional context
        additional_context = st.text_area(
            "Additional Context",
            placeholder="Add any specific requirements or focus areas you want the AI to consider when generating new searches...",
            help="This context will be used to influence the generated search queries along with the search history."
        )
        
        if st.button("Generate New Queries", type="primary"):
            with st.spinner("Generating new search queries..."):
                run_async_operation(expand_searches, additional_context)
            st.success("New queries generated!")
        
        # Display current searches
        st.subheader("Search History")
        show_new_only = st.checkbox("Show only new searches", value=True)
        get_searches_table(show_new_only)

    # Send Emails Page
    elif page == "Send Emails":
        st.title("📧 Send Emails")
        st.write("Select leads to create email drafts in Zoho.")
        
        try:
            # Get leads data
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            leads = service.spreadsheets().values().get(
                spreadsheetId=st.session_state.spreadsheet_id,
                range='leads!A:L'
            ).execute().get('values', [])
            
            if len(leads) > 1:  # If we have data beyond headers
                headers = leads[0]
                data = leads[1:]
                
                # Convert to DataFrame for easier manipulation
                df = pd.DataFrame(data, columns=headers)
                
                # Filter rows with email addresses
                df = df[df['Email'].notna() & (df['Email'] != '')]
                
                # Filter out already emailed leads if they exist
                if 'Emailed?' in df.columns:
                    df = df[df['Emailed?'].fillna('').str.lower() == '']
                
                if len(df) > 0:
                    # Initialize session state for selected leads if not exists
                    if 'selected_leads' not in st.session_state:
                        st.session_state.selected_leads = []
                    
                    # Create selection column
                    df['Select'] = False
                    
                    # Reorder columns to put Select first
                    cols = ['Select'] + [col for col in df.columns if col != 'Select']
                    df = df[cols]
                    
                    # Display stats
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Available Leads", len(df))
                    with col2:
                        st.metric("Selected for Batch", len(st.session_state.selected_leads))
                    
                    st.markdown("---")
                    
                    # Add search functionality
                    search_query = st.text_input(
                        "🔍 Search leads by name or website",
                        placeholder="Enter search terms...",
                        help="Filter the table by searching across names and websites"
                    )
                    
                    # Filter dataframe if search query exists
                    if search_query:
                        mask = (
                            df['Org Name'].fillna('').str.lower().str.contains(search_query.lower()) |
                            df['Link'].fillna('').str.lower().str.contains(search_query.lower())
                        )
                        filtered_df = df[mask]
                        if len(filtered_df) == 0:
                            st.info("No matches found.")
                            display_df = df  # Show all results if no matches
                        else:
                            display_df = filtered_df
                    else:
                        display_df = df
                    
                    # Create the dataframe editor
                    edited_df = st.data_editor(
                        display_df,
                        column_config={
                            "Select": st.column_config.CheckboxColumn(
                                "Select",
                                help="Select leads for batch processing",
                                default=False
                            )
                        },
                        hide_index=True,
                        key="leads_editor"
                    )
                    
                    # Update selected leads based on checkboxes
                    selected_indices = edited_df[edited_df['Select']].index
                    selected_rows = edited_df.loc[selected_indices]
                    
                    # Create batch processing button
                    if len(selected_rows) > 0:
                        if st.button(f"Process {len(selected_rows)} Selected Leads", type="primary"):
                            with st.spinner("Creating email drafts..."):
                                # Prepare contacts list with normalized URLs
                                contacts = list(zip(
                                    [normalize_url(url) for url in selected_rows['Link'].tolist()],
                                    selected_rows['Email'].tolist()
                                ))
                                
                                try:
                                    # Create drafts
                                    create_multiple_drafts(
                                        ZOHO_MAIL_CLIENT_ID,
                                        ZOHO_MAIL_CLIENT_SECRET,
                                        ZOHO_MAIL_REFRESH_TOKEN,
                                        contacts,
                                        "matt@zakaya.io"  # TODO: Make this configurable
                                    )
                                    st.success(f"Successfully created {len(contacts)} email drafts!")
                                    
                                    # Clear selections
                                    st.session_state.selected_leads = []
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"Error creating drafts: {str(e)}")
                    else:
                        st.info("Select leads to process by checking the boxes in the table.")
                else:
                    st.info("No leads available for email processing.")
            else:
                st.info("No leads found in the sheet.")
        except Exception as e:
            st.error(f"Error loading leads: {str(e)}")

    # Create New Sheet Page
    elif page == "Create New Sheet":
        st.title("📝 Create New Spreadsheet")
        st.write("Create a new Google Sheet with the required structure for lead generation.")
        
        # Input fields
        sheet_title = st.text_input(
            "Sheet Title",
            placeholder="e.g., Lead Generation - Project X",
            help="Enter a descriptive title for your new spreadsheet"
        )
        
        email = st.text_input(
            "Share with Email",
            placeholder="user@example.com",
            help="The spreadsheet will be shared with this email address"
        )
        
        if st.button("Create Spreadsheet", type="primary"):
            if not sheet_title or not email:
                st.warning("Please enter both a title and an email address.")
            else:
                with st.spinner("Creating and configuring spreadsheet..."):
                    try:
                        service = connect_to_sheets(st.session_state.spreadsheet_id)
                        new_spreadsheet_id = create_new_spreadsheet(service, sheet_title, email)
                        
                        if new_spreadsheet_id:
                            st.session_state.spreadsheet_id = new_spreadsheet_id
                            st.success(f"""
                            ✅ Spreadsheet created successfully!
                            
                            The spreadsheet has been:
                            1. Created with all required sheets and columns
                            2. Shared with {email}
                            3. Set as the active spreadsheet
                            
                            You can now use other pages to start working with this spreadsheet.
                            """)
                            
                            # Add a link to open the spreadsheet
                            st.markdown(f"[Open Spreadsheet](https://docs.google.com/spreadsheets/d/{new_spreadsheet_id})")
                        else:
                            st.error("Failed to create spreadsheet. Please try again.")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        # Add some helpful information
        st.markdown("---")
        st.markdown("""
        ### About the Spreadsheet Structure
        
        The new spreadsheet will be created with three sheets:
        
        1. **Sources Sheet**
        - Columns: Title, URL, Description, Date Found, Status, Leads Found
        - Used to track potential lead sources
        
        2. **Leads Sheet**
        - Columns: Name, URL, Phone, Email, Notes
        - Stores extracted lead information
        
        3. **Searches Sheet**
        - Columns: Date, Query, Returns
        - Logs search queries and their results
        """)

    # New page for configuring email templates
    elif page == "Configure Templates":
        st.title("⚙️ Configure Email Templates")
        st.write("Customize email templates for different business types.")
        
        # Initialize state for template editing
        if 'current_templates' not in st.session_state:
            st.session_state.current_templates = EMAIL_TEMPLATES.copy()
        
        # Add tabs for different aspects of templates
        tab1, tab2 = st.tabs(["Email Templates", "Business Context"])
        
        with tab1:
            # Create a selector for which template to edit
            template_type = st.selectbox(
                "Select Template Type", 
                options=list(st.session_state.current_templates.keys()),
                format_func=lambda x: x.replace('_', ' ').title()
            )
            
            st.subheader(f"Edit {template_type.replace('_', ' ').title()} Template")
            
            # Get the current template values
            current_template = st.session_state.current_templates[template_type]
            
            # Create form fields
            subject = st.text_input(
                "Subject Line Template", 
                value=current_template["subject"],
                help="You can use {business_name} as a placeholder for the business name"
            )
            
            main_pitch = st.text_area(
                "Main Pitch", 
                value=current_template["main_pitch"],
                height=150,
                help="This is the main value proposition. HTML formatting is supported."
            )
            
            extra_context = st.text_area(
                "Extra Context for LLM", 
                value=current_template["extra_context"],
                height=150,
                help="This context helps the AI understand the purpose of this template."
            )
            
            # Update button
            if st.button("Update Template"):
                # Update the template in session state
                st.session_state.current_templates[template_type] = {
                    "subject": subject,
                    "main_pitch": main_pitch,
                    "extra_context": extra_context
                }
                # Save to cache
                cache_data = st.session_state.current_templates.copy()
                if 'context' in st.session_state and st.session_state.context:
                    cache_data['context'] = st.session_state.context
                else:
                    cache_data['context'] = ZAKAYA_CONTEXT
                save_templates_to_cache(cache_data)
                st.success(f"Updated {template_type} template!")
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Add button to create a new template type
                st.subheader("Add New Template")
                new_template_name = st.text_input(
                    "New Template Type",
                    placeholder="e.g., yoga_studio",
                    help="Enter a unique identifier for the new template (use lowercase with underscores)"
                )
                
                if st.button("Add New Template") and new_template_name:
                    # Validate name
                    if new_template_name in st.session_state.current_templates:
                        st.error(f"Template '{new_template_name}' already exists!")
                    elif ' ' in new_template_name or not new_template_name.islower():
                        st.warning("Template name should be lowercase with underscores instead of spaces")
                    else:
                        # Add new template with default values
                        st.session_state.current_templates[new_template_name] = {
                            "subject": "Community Platform for {business_name}",
                            "main_pitch": """<p style="margin: 0 0 1em 0;">Our platform could help create a <span style="font-weight: bold;">vibrant online community</span> around your business!</p>""",
                            "extra_context": "We are looking to sell these businesses on the idea of creating an online community around their activities."
                        }
                        # Save to cache
                        cache_data = st.session_state.current_templates.copy()
                        if 'context' in st.session_state and st.session_state.context:
                            cache_data['context'] = st.session_state.context
                        else:
                            cache_data['context'] = ZAKAYA_CONTEXT
                        save_templates_to_cache(cache_data)
                        st.success(f"Added new template: {new_template_name}")
                        # Force a rerun to update the selectbox
                        st.rerun()
            
            with col2:
                # Add option to delete a template
                st.subheader("Remove Template")
                template_to_delete = st.selectbox(
                    "Select Template to Remove",
                    options=list(st.session_state.current_templates.keys()),
                    format_func=lambda x: x.replace('_', ' ').title()
                )
                
                if st.button("Delete Template") and template_to_delete:
                    # Remove the template
                    if len(st.session_state.current_templates) <= 1:
                        st.error("Cannot delete the only remaining template!")
                    else:
                        del st.session_state.current_templates[template_to_delete]
                        # Save to cache
                        cache_data = st.session_state.current_templates.copy()
                        if 'context' in st.session_state and st.session_state.context:
                            cache_data['context'] = st.session_state.context
                        else:
                            cache_data['context'] = ZAKAYA_CONTEXT
                        save_templates_to_cache(cache_data)
                        st.success(f"Deleted template: {template_to_delete}")
                        # Force a rerun to update the selectbox
                        st.rerun()
        
        with tab2:
            st.subheader("Global Business Context")
            st.write("This context is used by our AI to understand your business when generating email content.")
            
            # Store context in session state for persistence
            if 'context' not in st.session_state:
                st.session_state.context = ZAKAYA_CONTEXT
            
            # Main context editor
            context_editor = st.text_area(
                "Edit Business Context",
                value=st.session_state.context,
                height=300,
                help="This context helps the AI understand your business and its value proposition."
            )
            
            # Update context button
            if st.button("Update Business Context"):
                st.session_state.context = context_editor
                # Save to cache with templates
                cache_data = st.session_state.current_templates.copy()
                cache_data['context'] = context_editor
                save_templates_to_cache(cache_data)
                st.success("Updated business context!")
            
            st.markdown("---")
            
            # AI-powered context improvement
            st.subheader("Improve Context with AI")
            st.write("Let our AI help you improve your business context.")
            
            improvement_input = st.text_area(
                "What would you like to improve?",
                placeholder="Describe what aspects of your context you'd like to improve and any additional information about your business that might help the AI...",
                height=150,
                help="You can mention specific focus areas (like clarity, persuasiveness) and include any additional business details not reflected in the current context."
            )
            
            if st.button("Generate Improved Context", type="primary"):
                if not improvement_input:
                    st.error("Please describe what you'd like to improve.")
                else:
                    with st.spinner("Generating improved context..."):
                        # Prepare the prompt for the LLM
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
                                
                                {st.session_state.context}
                                
                                The user would like to improve this context:
                                
                                {improvement_input}
                                
                                Please provide an improved context that maintains the same structure (numbered list) but incorporates the user's feedback.
                                """
                            }
                        ]
                        
                        # Get response from LLM
                        improved_context = _llm(messages)
                        
                        if improved_context:
                            # Update the editor with the improved context
                            st.session_state.context = improved_context
                            # Save to cache
                            cache_data = st.session_state.current_templates.copy()
                            cache_data['context'] = improved_context
                            save_templates_to_cache(cache_data)
                            st.success("Generated improved context!")
                            st.info("The context editor has been updated with the AI-generated content. You can make further edits as needed.")
                            # Rerun to show the updated context in the editor
                            st.rerun()
                        else:
                            st.error("Failed to generate improved context. Please try again.")
            
            st.markdown("---")
            
            # Reset option
            st.subheader("Reset to Default")
            if st.button("Reset Business Context to Default"):
                # Reset context to default
                st.session_state.context = DEFAULT_ZAKAYA_CONTEXT
                
                # Save to cache with templates
                cache_data = st.session_state.current_templates.copy()
                cache_data['context'] = DEFAULT_ZAKAYA_CONTEXT
                save_templates_to_cache(cache_data)
                
                st.success("Reset business context to default values")
                # Force a rerun to update the editor
                st.rerun()

    # Add option to reset all templates to default
    if st.button("Reset All Templates and Context to Default"):
        # Create a copy of the default templates
        reset_data = DEFAULT_EMAIL_TEMPLATES.copy()
        # Add default context
        reset_data['context'] = DEFAULT_ZAKAYA_CONTEXT
        
        # Save to cache and update session state
        save_templates_to_cache(reset_data)
        st.session_state.current_templates = DEFAULT_EMAIL_TEMPLATES.copy()
        if 'context' in st.session_state:
            st.session_state.context = DEFAULT_ZAKAYA_CONTEXT
        st.success("Reset all templates and business context to default values")
        # Force a rerun
        st.rerun()

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("### About")
    st.sidebar.info(
        """
        This tool helps you generate and manage leads by:
        - Running targeted searches
        - Processing existing sources
        - Generating new search queries
        """
    )