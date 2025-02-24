import json
import streamlit as st
from app.core.models import parser_search_query_list
from app.llm.llm import _llm
from app.utils.gcs import get_sheet_data, write_to_suggested_searches_sheet, connect_to_sheets
from app.llm.prompts import USER_BUSINESS_MESSAGE, EXPAND_SEARCH_PROMPT

async def generate_search_queries(service, spreadsheet_id, additional_context=""):
    """Generate new search queries based on search history"""
    print("\nAnalyzing search history to generate new queries...")
    
    # Get search history
    searches = get_sheet_data(service, spreadsheet_id, 'searches!A:C')
    
    # Format search history for LLM, filtering out rows where Returns is "new"
    headers = searches[0]
    search_history = []
    for row in searches[1:]:
        if len(row) >= 3 and row[2].lower() != "new":  # Ensure row has all columns and Returns isn't "new"
            search_history.append({
                'query': row[1],
            })
    
    # Prepare message for LLM
    messages = [
        {"role": "system", "content": EXPAND_SEARCH_PROMPT.render(format_instruction=parser_search_query_list.get_format_instructions())},
        {"role": "user", "content": USER_BUSINESS_MESSAGE}
    ]

    # Add additional context if provided
    if additional_context:
        messages.append({"role": "user", "content": f"Additional context to consider when generating queries: {additional_context}"})

    if search_history:
        messages.append({"role": "user", "content": f"Here is the search history of successful queries, please analyze it and suggest new search queries:\n{json.dumps(search_history, indent=2)}"})
    else:
        messages.append({"role": "user", "content": "No search history found. Use the user's business message to generate new search queries."})
    
    # Get LLM response
    response = _llm(messages)
    if response:
        try:
            result = parser_search_query_list.parse(response)
            print(f"\nGenerated {len(result.SearchQueries)} new search queries:")
            for query in result.SearchQueries:
                print(f"- {query}")
            return result.SearchQueries
        except Exception as e:
            print(f"Error parsing LLM response: {e}")
            print(f"Raw response: {response}")
    
    return []



async def expand_searches(additional_context=""):
    """Generate new search queries based on search history and write them to searches sheet"""
    # Connect to Google Sheets
    service = connect_to_sheets(st.session_state.spreadsheet_id)
    
    # Generate new queries
    new_queries = await generate_search_queries(service, st.session_state.spreadsheet_id, additional_context)
    
    if new_queries:
        print(f"\nWriting {len(new_queries)} suggested queries to sheet...")
        write_to_suggested_searches_sheet(service, st.session_state.spreadsheet_id, new_queries)
        print("\nSuggested queries have been written to the 'searches' sheet for review")
    else:
        print("No new search queries generated")
