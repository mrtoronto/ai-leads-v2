import streamlit as st
import pandas as pd
import logging

import asyncio
from app.core.check_sources import check_sources
from app.core.expand_search import expand_searches
from app.core.run_search import search_and_write, run_multiple_searches
from app.core.create_zoho_drafts import (
    create_multiple_drafts, 
    ZOHO_MAIL_CLIENT_ID, 
    ZOHO_MAIL_CLIENT_SECRET, 
    ZOHO_MAIL_REFRESH_TOKEN,
    normalize_url
)
from app.core.create_sendgrid_emails import generate_emails_for_contacts, send_single_email
from app.utils.gcs import (
    connect_to_sheets, 
    create_new_spreadsheet,
    get_spreadsheet_metadata
)
from app.utils.cache import get_spreadsheet_id_from_cache, save_spreadsheet_id_to_cache
from app.utils.template_cache import save_templates_to_cache
from app.llm.email_template import EMAIL_TEMPLATES, DEFAULT_EMAIL_TEMPLATES, ZAKAYA_CONTEXT, DEFAULT_ZAKAYA_CONTEXT
from app.llm.llm import _llm
from app.local_settings import (
    GMAIL_USER_EMAIL,
    firestore_creds
)
# Import the new sheet cache module
from app.utils.sheet_cache import (
    get_sheet_data_cached, 
    update_cache_after_write, 
    clear_cache, 
    get_cache_info,
    load_all_sheets
)

def get_searches_table(show_only_new=False, with_checkboxes=False):
    """Helper function to display searches table with optional checkboxes"""
    try:
        service = connect_to_sheets(st.session_state.spreadsheet_id)
        
        # Use cached data instead of direct API call
        df = get_sheet_data_cached(service, st.session_state.spreadsheet_id, 'searches')
        
        if df is not None and not df.empty:
            # Filter based on show_only_new flag - show completed by default
            if not show_only_new:  # When checkbox is unchecked, show completed searches
                filtered_df = df[df['Returns'].fillna('').str.lower() != 'new']
                if len(filtered_df) == 0:
                    st.info("No completed searches found.")
                    return None
            else:  # When checkbox is checked, show new searches
                filtered_df = df[df['Returns'].fillna('').str.lower() == 'new']
                if len(filtered_df) == 0:
                    st.info("No new searches found.")
                    return None
            
            # Add checkboxes if requested
            if with_checkboxes:
                filtered_df['Select'] = False
                # Reorder columns to put Select first
                cols = ['Select'] + [col for col in filtered_df.columns if col != 'Select']
                filtered_df = filtered_df[cols]
                
                # Display the DataFrame with checkboxes
                edited_df = st.data_editor(
                    filtered_df,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(
                            "Select",
                            help="Select searches to run in batch",
                            default=False
                        )
                    },
                    hide_index=True,
                    key="searches_editor"
                )
                return edited_df
            else:
                # Just display the DataFrame without checkboxes
                st.dataframe(filtered_df, hide_index=True)
                return None
        else:
            st.info("No search history found.")
            return None
    except Exception as e:
        st.error(f"Error loading search history: {str(e)}")
        return None

def get_source_stats():
    """Helper function to calculate source statistics"""
    try:
        service = connect_to_sheets(st.session_state.spreadsheet_id)
        
        # Use cached data instead of direct API call
        df = get_sheet_data_cached(service, st.session_state.spreadsheet_id, 'sources')
        
        if df is not None and not df.empty:
            total_sources = len(df)
            checked_sources = df[df['Status'] == 'checked'].shape[0]
            new_sources = df[df['Status'] == 'new'].shape[0]
            
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
        "Select a Page", [
            "Create New Sheet", 
            "Generate Searches", 
            "Run Search", 
            "Check Sources",
            "Check Leads",  # Add new page
            "Send Emails via Gmail", 
            "Configure Templates"
        ]
    )

    # Spreadsheet ID configuration
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Configuration")

    # Show current spreadsheet info
    try:
        if st.session_state.spreadsheet_id:  # Only try to connect if we have an ID
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            
            # Use cached metadata if available
            if 'sheet_cache' in st.session_state and st.session_state.sheet_cache.get('metadata'):
                sheet_info = {
                    'title': st.session_state.sheet_cache['metadata']['properties']['title'],
                    'url': f"https://docs.google.com/spreadsheets/d/{st.session_state.spreadsheet_id}"
                }
            else:
                sheet_info = get_spreadsheet_metadata(service, st.session_state.spreadsheet_id)
                
            if sheet_info:
                st.sidebar.markdown(f"**Current Sheet:** [{sheet_info['title']}]({sheet_info['url']})")
                
                # Load all sheets into cache if not already initialized
                if not st.session_state.get('cache_initialized', False):
                    # Create an empty placeholder in the sidebar
                    sidebar_status = st.sidebar.empty()
                    sidebar_status.info("Loading data...")
                    
                    # Load the data
                    load_all_sheets(service, st.session_state.spreadsheet_id)
                    
                    # Update the placeholder with success message
                    sidebar_status.success("Data loaded!")
    except Exception as e:
        st.sidebar.warning(f"Unable to fetch sheet information: {str(e)}")

    new_spreadsheet_id = st.sidebar.text_input(
        "Google Sheet ID",
        value=st.session_state.spreadsheet_id,
        help="The ID of the Google Sheet to use (from the URL)"
    )

    # Update spreadsheet ID if changed
    if new_spreadsheet_id != st.session_state.spreadsheet_id:
        # Clear cache when changing spreadsheets
        clear_cache()
        st.session_state.spreadsheet_id = new_spreadsheet_id
        save_spreadsheet_id_to_cache(new_spreadsheet_id)  # Save to cache when updated
        st.rerun()

    # Add a refresh button to the sidebar
    cache_info = get_cache_info()
    if cache_info['initialized']:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Cache Status")
        
        cache_status = (
            f"✅ {cache_info['sheets_cached']} sheets cached\n\n"
            f"📄 Sheets: {', '.join(cache_info['sheet_names'])}\n\n"
            f"🕒 Last updated: {cache_info['newest_cache']}"
        )
        st.sidebar.markdown(cache_status)
        
        if st.sidebar.button("🔄 Refresh Data", type="primary"):
            # Create an empty placeholder in the sidebar
            refresh_status = st.sidebar.empty()
            refresh_status.info("Refreshing data...")
            
            # Refresh the data
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            load_all_sheets(service, st.session_state.spreadsheet_id, force_refresh=True)
            
            # Update the placeholder with success message
            refresh_status.success("Data refreshed!")
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
            # Refresh cache after operation completes
            if st.session_state.spreadsheet_id:
                service = connect_to_sheets(st.session_state.spreadsheet_id)
                load_all_sheets(service, st.session_state.spreadsheet_id, force_refresh=True)
            st.rerun()

    # New Search Page
    if page == "Run Search":
        st.title("🔍 Run Search")
        st.write("Enter a search query to find potential leads.")
        
        # Create tabs for single search and batch search
        search_tab1, search_tab2 = st.tabs(["Run Single Search", "Run Multiple Searches"])
        
        with search_tab1:
            # Manual search entry (existing functionality)
            search_query = st.text_input(
                "Search Query",
                placeholder="e.g., Co-working spaces in California doing community events"
            )
            
            if st.button("Run Search", type="primary", key="single_search_button"):
                if search_query:
                    with st.spinner("Running search..."):
                        # Capture the return values from the search function
                        def run_single_search():
                            results_count, elapsed_time = asyncio.run(search_and_write(search_query))
                            st.session_state.last_search_results = {
                                "count": results_count,
                                "time": elapsed_time
                            }
                        
                        if not st.session_state.running:
                            st.session_state.running = True
                            run_single_search()
                            st.session_state.running = False
                    
                    # Display detailed success message with timing
                    if hasattr(st.session_state, 'last_search_results'):
                        results = st.session_state.last_search_results
                        st.success(
                            f"Search completed in {results['time']:.1f} seconds! "
                            f"Found {results['count']} relevant results."
                        )
                    else:
                        st.success("Search completed!")
                else:
                    st.warning("Please enter a search query.")
        
        with search_tab2:
            # Display search history with checkboxes
            st.subheader("Select Searches to Run")
            show_new_only = st.checkbox("Show only new searches", value=True, key="batch_show_new")
            
            edited_df = get_searches_table(show_new_only, with_checkboxes=True)
            
            if edited_df is not None and not edited_df.empty:
                # Get selected searches
                selected_indices = edited_df[edited_df['Select']].index
                selected_rows = edited_df.loc[selected_indices]
                
                if len(selected_rows) > 0:
                    if st.button(f"Run {len(selected_rows)} Selected Searches", type="primary", key="batch_search_button"):
                        # Extract search queries from selected rows
                        search_queries = selected_rows['Query'].tolist()
                        
                        with st.spinner(f"Running {len(search_queries)} searches sequentially..."):
                            # Capture the return values from the batch search function
                            def run_multiple_search():
                                batch_results = asyncio.run(run_multiple_searches(search_queries))
                                st.session_state.last_batch_results = batch_results
                            
                            if not st.session_state.running:
                                st.session_state.running = True
                                run_multiple_search()
                                st.session_state.running = False
                        
                        # Display detailed success message with timing
                        if hasattr(st.session_state, 'last_batch_results'):
                            results = st.session_state.last_batch_results
                            
                            # Create summary message
                            summary = f"Completed {len(results['queries'])} searches in {results['total_time']:.1f} seconds! Found {results['total_results']} total results."
                            st.success(summary)
                            
                            # Display per-query results in an expander
                            with st.expander("View detailed results by query"):
                                for idx, query_result in enumerate(results['queries']):
                                    st.markdown(
                                        f"**Query {idx+1}:** {query_result['query']}  \n"
                                        f"Results: {query_result['results_count']}  \n"
                                        f"Time: {query_result['time_taken']:.1f} seconds"
                                    )
                                    st.divider()
                        else:
                            st.success("All selected searches completed!")
                else:
                    st.info("Select searches to run by checking the boxes in the table.")
        
        # Display search history
        st.subheader("Previous Searches")
        show_new_only_history = st.checkbox("Show only new searches", value=True, key="history_show_new")
        get_searches_table(show_new_only_history)

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

    # Check Leads Page
    elif page == "Check Leads":
        st.title("📞 Check Leads")
        st.write("Process selected leads to update contact information and generate call notes.")
        
        try:
            # Get leads data from cache
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            leads_df = get_sheet_data_cached(service, st.session_state.spreadsheet_id, 'leads')
            
            if leads_df is not None and not leads_df.empty:
                # Filter out leads that have already been checked
                df = leads_df[leads_df['Checked?'].fillna('').str.lower() != 'checked']
                
                if len(df) > 0:
                    # Display stats
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Available Leads", len(df))
                    with col2:
                        st.metric("Already Checked", len(leads_df) - len(df))
                    
                    st.markdown("---")
                    
                    # Add search functionality
                    search_query = st.text_input(
                        "🔍 Search leads by name or website",
                        placeholder="Enter search terms...",
                        help="Filter the table by searching across names and websites",
                        key="check_leads_search"
                    )
                    
                    # Filter dataframe if search query exists
                    if search_query:
                        mask = (
                            df['Org Name'].fillna('').str.lower().str.contains(search_query.lower()) |
                            df['Link'].fillna('').str.lower().str.contains(search_query.lower())
                        )
                        filtered_df = df[mask].copy()  # Create an explicit copy
                        if len(filtered_df) == 0:
                            st.info("No matches found.")
                            display_df = df.copy()  # Create an explicit copy
                        else:
                            display_df = filtered_df
                    else:
                        display_df = df.copy()  # Create an explicit copy
                    
                    # Create selection column
                    display_df['Select'] = False
                    
                    # Reorder columns to put Select first
                    cols = ['Select'] + [col for col in display_df.columns if col != 'Select']
                    display_df = display_df[cols]
                    
                    # Create the dataframe editor
                    edited_df = st.data_editor(
                        display_df,
                        column_config={
                            "Select": st.column_config.CheckboxColumn(
                                "Select",
                                help="Select leads to check",
                                default=False
                            )
                        },
                        hide_index=True,
                        key="check_leads_editor"
                    )
                    
                    # Update selected leads based on checkboxes
                    selected_indices = edited_df[edited_df['Select']].index
                    selected_rows = edited_df.loc[selected_indices]
                    
                    # Create batch processing button
                    if len(selected_rows) > 0:
                        if st.button(f"Process {len(selected_rows)} Selected Leads", type="primary"):
                            with st.spinner("Checking leads for contact information and generating notes..."):
                                # Import the check_leads function
                                from app.core.check_leads import check_leads
                                
                                # Convert selected rows to list of dicts
                                selected_leads = selected_rows.to_dict('records')
                                
                                # Process the leads
                                run_async_operation(check_leads, selected_leads)
                                
                                st.success(f"Successfully processed {len(selected_leads)} leads!")
                                st.rerun()
                    else:
                        st.info("Select leads to process by checking the boxes in the table.")
                else:
                    st.info("No leads available for checking (all leads have been checked).")
            else:
                st.info("No leads found in the sheet.")
        except Exception as e:
            st.error(f"Error loading leads: {str(e)}")

    # Send Emails Page
    # elif page == "Send Emails via Zoho":
    #     st.title("📧 Send Emails via Zoho")
    #     st.write("Select leads to create email drafts in Zoho.")
        
    #     try:
    #         # Get leads data
    #         service = connect_to_sheets(st.session_state.spreadsheet_id)
    #         leads = service.spreadsheets().values().get(
    #             spreadsheetId=st.session_state.spreadsheet_id,
    #             range='leads!A:L'
    #         ).execute().get('values', [])
            
    #         if len(leads) > 1:  # If we have data beyond headers
    #             headers = leads[0]
    #             data = leads[1:]
                
    #             # Convert to DataFrame for easier manipulation
    #             df = pd.DataFrame(data, columns=headers)
                
    #             # Filter rows with email addresses
    #             df = df[df['Email'].notna() & (df['Email'] != '')]
                
    #             # Filter out already emailed leads if they exist
    #             if 'Emailed?' in df.columns:
    #                 df = df[df['Emailed?'].fillna('').str.lower() == '']
                
    #             if len(df) > 0:
    #                 # Initialize session state for selected leads if not exists
    #                 if 'selected_leads' not in st.session_state:
    #                     st.session_state.selected_leads = []
                    
    #                 # Create selection column
    #                 df['Select'] = False
                    
    #                 # Reorder columns to put Select first
    #                 cols = ['Select'] + [col for col in df.columns if col != 'Select']
    #                 df = df[cols]
                    
    #                 # Display stats
    #                 col1, col2 = st.columns(2)
    #                 with col1:
    #                     st.metric("Available Leads", len(df))
    #                 with col2:
    #                     st.metric("Selected for Batch", len(st.session_state.selected_leads))
                    
    #                 st.markdown("---")
                    
    #                 # Add search functionality
    #                 search_query = st.text_input(
    #                     "🔍 Search leads by name or website",
    #                     placeholder="Enter search terms...",
    #                     help="Filter the table by searching across names and websites"
    #                 )
                    
    #                 # Filter dataframe if search query exists
    #                 if search_query:
    #                     mask = (
    #                         df['Org Name'].fillna('').str.lower().str.contains(search_query.lower()) |
    #                         df['Link'].fillna('').str.lower().str.contains(search_query.lower())
    #                     )
    #                     filtered_df = df[mask]
    #                     if len(filtered_df) == 0:
    #                         st.info("No matches found.")
    #                         display_df = df  # Show all results if no matches
    #                     else:
    #                         display_df = filtered_df
    #                 else:
    #                     display_df = df
                    
    #                 # Create the dataframe editor
    #                 edited_df = st.data_editor(
    #                     display_df,
    #                     column_config={
    #                         "Select": st.column_config.CheckboxColumn(
    #                             "Select",
    #                             help="Select leads for batch processing",
    #                             default=False
    #                         )
    #                     },
    #                     hide_index=True,
    #                     key="leads_editor"
    #                 )
                    
    #                 # Update selected leads based on checkboxes
    #                 selected_indices = edited_df[edited_df['Select']].index
    #                 selected_rows = edited_df.loc[selected_indices]
                    
    #                 # Create batch processing button
    #                 if len(selected_rows) > 0:
    #                     if st.button(f"Process {len(selected_rows)} Selected Leads", type="primary"):
    #                         with st.spinner("Creating email drafts..."):
    #                             # Prepare contacts list with normalized URLs
    #                             contacts = list(zip(
    #                                 [normalize_url(url) for url in selected_rows['Link'].tolist()],
    #                                 selected_rows['Email'].tolist()
    #                             ))
                                
    #                             try:
    #                                 # Create drafts
    #                                 create_multiple_drafts(
    #                                     ZOHO_MAIL_CLIENT_ID,
    #                                     ZOHO_MAIL_CLIENT_SECRET,
    #                                     ZOHO_MAIL_REFRESH_TOKEN,
    #                                     contacts,
    #                                     "matt@zakaya.io"  # TODO: Make this configurable
    #                                 )
    #                                 st.success(f"Successfully created {len(contacts)} email drafts!")
                                    
    #                                 # Clear selections
    #                                 st.session_state.selected_leads = []
    #                                 st.rerun()
                                    
    #                             except Exception as e:
    #                                 st.error(f"Error creating drafts: {str(e)}")
    #                 else:
    #                     st.info("Select leads to process by checking the boxes in the table.")
    #             else:
    #                 st.info("No leads available for email processing.")
    #         else:
    #             st.info("No leads found in the sheet.")
    #     except Exception as e:
    #         st.error(f"Error loading leads: {str(e)}")

    # Send Emails via Gmail
    elif page == "Send Emails via Gmail":
        st.title("📧 Send Emails via Gmail")
        st.write("Select leads to create email drafts in Gmail.")
        
        # Gmail configuration - now using the setting from local_settings.py
        st.markdown("### Gmail Configuration")
        gmail_user_email = st.text_input(
            "Gmail User Email", 
            value=GMAIL_USER_EMAIL,
            help="The email address to send from"
        )
        
        # From email (optional)
        from_email = st.text_input(
            "From Email (optional)", 
            value=gmail_user_email,
            help="The email address that will appear in the 'From' field. Defaults to the Gmail user email."
        )
        
        # Password explanation
        st.info("You'll be prompted for your password when sending emails. For security, we don't store your password between sessions.")
        
        try:
            # Get leads data from cache
            service = connect_to_sheets(st.session_state.spreadsheet_id)
            leads_df = get_sheet_data_cached(service, st.session_state.spreadsheet_id, 'leads')
            
            if leads_df is not None and not leads_df.empty:
                # Filter rows with email addresses
                df = leads_df[leads_df['Email'].notna() & (leads_df['Email'].str.strip() != '') & (leads_df['Link'].str.strip() != '')]
                
                # Filter out already emailed leads if they exist
                if 'Emailed?' in df.columns:
                    df = df[df['Emailed?'].fillna('').str.lower() == '']
                
                if len(df) > 0:
                    # Initialize session state for selected leads if not exists
                    if 'selected_leads_gmail' not in st.session_state:
                        st.session_state.selected_leads_gmail = []
                    
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
                        st.metric("Selected for Batch", len(st.session_state.selected_leads_gmail))
                    
                    st.markdown("---")
                    
                    # Add search functionality
                    search_query = st.text_input(
                        "🔍 Search leads by name or website",
                        placeholder="Enter search terms...",
                        help="Filter the table by searching across names and websites",
                        key="gmail_search"
                    )
                    
                    # Filter dataframe if search query exists
                    if search_query:
                        mask = (
                            df['Org Name'].fillna('').str.lower().str.contains(search_query.lower()) |
                            df['Link'].fillna('').str.lower().str.contains(search_query.lower())
                        )
                        filtered_df = df[mask].copy()  # Create an explicit copy
                        if len(filtered_df) == 0:
                            st.info("No matches found.")
                            display_df = df.copy()  # Create an explicit copy
                        else:
                            display_df = filtered_df
                    else:
                        display_df = df.copy()  # Create an explicit copy
                    
                    # Create the dataframe editor with a key that doesn't change with selections
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
                        key="gmail_leads_editor_static"  # Static key to prevent reloading
                    )
                    
                    # Update selected leads based on checkboxes
                    selected_indices = edited_df[edited_df['Select']].index
                    selected_rows = edited_df.loc[selected_indices]
                    
                    # Create batch processing button
                    if len(selected_rows) > 0:
                        if st.button(f"Process {len(selected_rows)} Selected Leads", type="primary", key="gmail_process_button"):
                            # Prepare contacts list with normalized URLs
                            contacts = list(zip(
                                [normalize_url(url) for url in selected_rows['Link'].tolist()],
                                selected_rows['Email'].tolist(),
                                selected_rows['Notes'].tolist() if 'Notes' in selected_rows else [''] * len(selected_rows)
                            ))
                            
                            # Add a warning about not navigating away
                            st.warning("⚠️ Processing emails... Please do not navigate away from this page or refresh until complete!")
                            
                            # Create progress indicators
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            status_text.text(f"Starting to process {len(contacts)} email drafts...")
                            
                            try:
                                # Import the Gmail drafts function
                                from app.core.create_gmail_drafts import create_multiple_gmail_drafts
                                
                                # Create drafts
                                create_multiple_gmail_drafts(
                                    service_account_info=firestore_creds,
                                    user_email=gmail_user_email,
                                    contacts=contacts,
                                    from_email=from_email if from_email else None,
                                    spreadsheet_id=st.session_state.spreadsheet_id
                                )
                                
                                # Update progress to complete
                                progress_bar.progress(1.0)
                                status_text.text("✅ Processing complete!")
                                
                                # Force a cache refresh after processing
                                load_all_sheets(service, st.session_state.spreadsheet_id, force_refresh=True)
                                
                                st.success(f"Successfully created {len(contacts)} email drafts in Gmail!")
                                
                                # Clear selections
                                st.session_state.selected_leads_gmail = []
                                st.rerun()
                                
                            except Exception as e:
                                error_msg = str(e)
                                # Handle session stop gracefully
                                if 'streamlit' in error_msg.lower() and 'stop' in error_msg.lower():
                                    status_text.text("⏹️ Process was stopped")
                                    st.info("✋ Process was stopped. You can restart it by clicking the button again.")
                                else:
                                    status_text.text("❌ Error occurred")
                                    st.error(f"Error creating Gmail drafts: {error_msg}")
                                # Also log the full error for debugging
                                logging.error(f"Gmail drafts error: {error_msg}", exc_info=True)
                    else:
                        st.info("Select leads to process by checking the boxes in the table.")
                else:
                    st.info("No leads available for email processing.")
            else:
                st.info("No leads found in the sheet.")
        except Exception as e:
            st.error(f"Error loading leads: {str(e)}")

    # Send Emails via SendGrid Page
    # elif page == "Send via SendGrid":
    #     st.title("📧 Send Emails via SendGrid")
        
    #     # Initialize session states for email workflow
    #     if 'generated_emails' not in st.session_state:
    #         st.session_state.generated_emails = []
    #     if 'current_email_index' not in st.session_state:
    #         st.session_state.current_email_index = 0
    #     if 'generation_complete' not in st.session_state:
    #         st.session_state.generation_complete = False
        
    #     # Sender information
    #     st.markdown("### Sender Information")
    #     sender_col1, sender_col2 = st.columns(2)
    #     with sender_col1:
    #         from_email = st.text_input("From Email", value="matt@zakaya.io")
    #     with sender_col2:
    #         from_name = st.text_input("From Name", value="Matt from Zakaya")
        
    #     # Navigation tabs
    #     tab1, tab2 = st.tabs(["Select Leads", "Review & Send Emails"])
        
    #     with tab1:
    #         st.subheader("Step 1: Select Leads for Email Generation")
            
    #         try:
    #             # Get leads data
    #             service = connect_to_sheets(st.session_state.spreadsheet_id)
    #             leads = service.spreadsheets().values().get(
    #                 spreadsheetId=st.session_state.spreadsheet_id,
    #                 range='leads!A:L'
    #             ).execute().get('values', [])
                
    #             if len(leads) > 1:  # If we have data beyond headers
    #                 headers = leads[0]
    #                 data = leads[1:]
                    
    #                 # Convert to DataFrame for easier manipulation
    #                 df = pd.DataFrame(data, columns=headers)
                    
    #                 # Filter rows with email addresses
    #                 df = df[df['Email'].notna() & (df['Email'] != '')]
                    
    #                 # Filter out already emailed leads if they exist
    #                 if 'Emailed?' in df.columns:
    #                     df = df[df['Emailed?'].fillna('').str.lower() == '']
                    
    #                 if len(df) > 0:
    #                     # Create selection column
    #                     df['Select'] = False
                        
    #                     # Reorder columns to put Select first
    #                     cols = ['Select'] + [col for col in df.columns if col != 'Select']
    #                     df = df[cols]
                        
    #                     # Display stats
    #                     col1, col2 = st.columns(2)
    #                     with col1:
    #                         st.metric("Available Leads", len(df))
    #                     with col2:
    #                         st.metric("Generated Emails", len(st.session_state.generated_emails))
                        
    #                     st.markdown("---")
                        
    #                     # Add search functionality
    #                     search_query = st.text_input(
    #                         "🔍 Search leads by name or website",
    #                         placeholder="Enter search terms...",
    #                         help="Filter the table by searching across names and websites",
    #                         key="sendgrid_search"
    #                     )
                        
    #                     # Filter dataframe if search query exists
    #                     if search_query:
    #                         mask = (
    #                             df['Org Name'].fillna('').str.lower().str.contains(search_query.lower()) |
    #                             df['Link'].fillna('').str.lower().str.contains(search_query.lower())
    #                         )
    #                         filtered_df = df[mask]
    #                         if len(filtered_df) == 0:
    #                             st.info("No matches found.")
    #                             display_df = df  # Show all results if no matches
    #                         else:
    #                             display_df = filtered_df
    #                     else:
    #                         display_df = df
                        
    #                     # Create the dataframe editor
    #                     edited_df = st.data_editor(
    #                         display_df,
    #                         column_config={
    #                             "Select": st.column_config.CheckboxColumn(
    #                                 "Select",
    #                                 help="Select leads for generating emails",
    #                                 default=False
    #                             )
    #                         },
    #                         hide_index=True,
    #                         key="sendgrid_leads_editor"
    #                     )
                        
    #                     # Update selected leads based on checkboxes
    #                     selected_indices = edited_df[edited_df['Select']].index
    #                     selected_rows = edited_df.loc[selected_indices]
                        
    #                     # Create generate emails button
    #                     if len(selected_rows) > 0:
    #                         if st.button(
    #                             f"Generate {len(selected_rows)} Emails for Review", 
    #                             type="primary"
    #                         ):
    #                             # Prepare contacts list with normalized URLs
    #                             contacts = list(zip(
    #                                 [normalize_url(url) for url in selected_rows['Link'].tolist()],
    #                                 selected_rows['Email'].tolist()
    #                             ))
                                
    #                             with st.spinner("Generating personalized emails..."):
    #                                 try:
    #                                     # Generate emails
    #                                     generated_emails = generate_emails_for_contacts(
    #                                         contacts,
    #                                         service=service,
    #                                         spreadsheet_id=st.session_state.spreadsheet_id
    #                                     )
                                        
    #                                     # Store in session state
    #                                     st.session_state.generated_emails = generated_emails
    #                                     st.session_state.current_email_index = 0
    #                                     st.session_state.generation_complete = True
                                        
    #                                     st.success(f"Successfully generated {len(generated_emails)} emails for review!")
    #                                     st.info("Go to the 'Review & Send Emails' tab to preview and send emails")
                                        
    #                                 except Exception as e:
    #                                     st.error(f"Error generating emails: {str(e)}")
    #                     else:
    #                         st.info("Select leads to generate emails by checking the boxes in the table.")
    #                 else:
    #                     st.info("No leads available for email processing.")
    #             else:
    #                 st.info("No leads found in the sheet.")
    #         except Exception as e:
    #             st.error(f"Error loading leads: {str(e)}")
        
    #     with tab2:
    #         st.subheader("Step 2: Review and Send Emails")
            
    #         if not st.session_state.generated_emails:
    #             st.info("No emails have been generated yet. Go to the 'Select Leads' tab to generate emails.")
    #         else:
    #             # Display number of emails and progress
    #             emails_count = len(st.session_state.generated_emails)
    #             current_index = st.session_state.current_email_index
                
    #             # Email navigation
    #             col1, col2, col3 = st.columns([1, 4, 1])
    #             with col1:
    #                 if current_index > 0:
    #                     if st.button("← Previous"):
    #                         st.session_state.current_email_index -= 1
    #                         st.rerun()
                
    #             with col2:
    #                 st.progress((current_index + 1) / emails_count)
    #                 st.markdown(f"**Reviewing Email {current_index + 1} of {emails_count}**")
                
    #             with col3:
    #                 if current_index < emails_count - 1:
    #                     if st.button("Next →"):
    #                         st.session_state.current_email_index += 1
    #                         st.rerun()
                
    #             # Display current email
    #             current_email = st.session_state.generated_emails[current_index]
                
    #             # Email details
    #             st.markdown("### Email Details")
    #             st.markdown(f"**To:** {current_email['email']} *(Will be sent to {from_email})*")
    #             st.markdown(f"**Subject:** {current_email['subject']}")
    #             st.markdown(f"**Website:** [{current_email['website']}]({current_email['website']})")
                
    #             # Preview tabs
    #             preview_tab1, preview_tab2, preview_tab3 = st.tabs(["HTML Preview", "Edit HTML", "Plain Text (Optional)"])
                
    #             with preview_tab1:
    #                 # Create a proper rendered HTML preview
    #                 html_preview = f"""
    #                 <div style="border: 1px solid #ddd; border-radius: 5px; padding: 20px; background-color: white;">
    #                     {current_email['html_content']}
    #                 </div>
    #                 """
    #                 st.components.v1.html(html_preview, height=500, scrolling=True)
                
    #             with preview_tab2:
    #                 # Add HTML editor with current content
    #                 if 'edited_html' not in st.session_state or st.session_state.current_email_index != st.session_state.last_edited_index:
    #                     st.session_state.edited_html = current_email['html_content']
    #                     st.session_state.last_edited_index = st.session_state.current_email_index
                    
    #                 edited_html = st.text_area(
    #                     "Edit HTML Content", 
    #                     st.session_state.edited_html, 
    #                     height=400
    #                 )
                    
    #                 # Update the edited HTML in session state
    #                 if edited_html != st.session_state.edited_html:
    #                     st.session_state.edited_html = edited_html
    #                     # Update the email in the list with edited content
    #                     current_email['html_content'] = edited_html
    #                     st.session_state.generated_emails[current_index] = current_email
                    
    #                 # Add a button to preview changes
    #                 if st.button("Preview Changes"):
    #                     st.markdown("### Preview of Edited HTML:")
    #                     preview_edited = f"""
    #                     <div style="border: 1px solid #ddd; border-radius: 5px; padding: 20px; background-color: white;">
    #                         {edited_html}
    #                     </div>
    #                     """
    #                     st.components.v1.html(preview_edited, height=400, scrolling=True)
                
    #             with preview_tab3:
    #                 include_plain_text = st.checkbox("Include plain text version", value=False)
    #                 if include_plain_text:
    #                     current_email['text_content'] = st.text_area(
    #                         "Plain Text Version", 
    #                         current_email['text_content'], 
    #                         height=300
    #                     )
    #                 else:
    #                     st.info("Plain text version is optional. Many email clients can auto-generate it from HTML.")
                
    #             # Send button
    #             col1, col2 = st.columns([3, 1])
    #             with col2:
    #                 if st.button("Send Email", type="primary"):
    #                     with st.spinner("Sending email..."):
    #                         service = connect_to_sheets(st.session_state.spreadsheet_id)
    #                         success = send_single_email(
    #                             current_email,
    #                             from_email=from_email,
    #                             from_name=from_name,
    #                             service=service,
    #                             spreadsheet_id=st.session_state.spreadsheet_id,
    #                             include_plain_text=include_plain_text
    #                         )
                            
    #                         if success:
    #                             st.success("Email sent successfully!")
                                
    #                             # Remove sent email from list
    #                             st.session_state.generated_emails.pop(current_index)
                                
    #                             if len(st.session_state.generated_emails) == 0:
    #                                 st.session_state.generation_complete = False
    #                                 st.rerun()
    #                             elif current_index >= len(st.session_state.generated_emails):
    #                                 st.session_state.current_email_index = len(st.session_state.generated_emails) - 1
    #                                 st.rerun()
    #                             else:
    #                                 st.rerun()
    #                         else:
    #                             st.error("Failed to send email. Please try again.")
                
    #             with col1:
    #                 if st.button("Skip this email"):
    #                     # Remove email from list without sending
    #                     st.session_state.generated_emails.pop(current_index)
                        
    #                     if len(st.session_state.generated_emails) == 0:
    #                         st.session_state.generation_complete = False
    #                         st.rerun()
    #                     elif current_index >= len(st.session_state.generated_emails):
    #                         st.session_state.current_email_index = len(st.session_state.generated_emails) - 1
    #                         st.rerun()
    #                     else:
    #                         st.rerun()

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