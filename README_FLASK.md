# Flask Lead Generation Tool

A minimal Flask web application that replaces the Streamlit app for lead generation, providing the same functionality with better performance and no timeout issues.

## Features

- **Create New Sheet**: Create Google Sheets with the required structure
- **Generate Searches**: AI-powered search query generation based on history
- **Run Search**: Execute single or batch searches for leads
- **Check Sources**: Process sources to find contact information
- **Check Leads**: Update lead information and generate call notes
- **Send Emails**: Create Gmail drafts for selected leads
- **Configure Templates**: Customize email templates and business context

## Installation

1. Install Poetry if you haven't already:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```bash
poetry install
```

3. Set up environment variables:
```bash
export SECRET_KEY="your-secret-key-here"
```

4. Run the Flask app:
```bash
poetry run python flask_app.py
```

The app will be available at `http://localhost:5000`

## Key Improvements over Streamlit

- **No timeout issues**: Long-running operations work without interruption
- **Better performance**: Faster page loads and data processing
- **Session management**: Proper session handling for user data
- **Clean UI**: Minimal, responsive design that works on all devices
- **AJAX operations**: Background processing without page reloads

## Usage

1. Enter your Google Sheet ID on the home page
2. Use the navigation menu to access different features
3. All operations provide real-time feedback and progress indicators
4. Data is cached for better performance with manual refresh option

## Architecture

- **Backend**: Flask with async support for long-running operations
- **Frontend**: Vanilla JavaScript with minimal dependencies
- **Styling**: Clean, minimal CSS with responsive design
- **Data**: Google Sheets integration with caching layer

## Development

To run in development mode with auto-reload:
```bash
poetry run flask run --debug
```

To activate the Poetry shell:
```bash
poetry shell