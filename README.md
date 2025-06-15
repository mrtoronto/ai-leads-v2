# Zakaya Lead Generation Tool

A Flask-based web application for generating and managing leads for Zakaya, including automated email drafting capabilities.

## Features

- **Create New Sheet**: Set up Google Sheets with the required structure
- **Generate Searches**: AI-powered search query generation based on history
- **Run Search**: Execute single or batch searches for leads
- **Check Sources**: Process sources to find contact information
- **Check Leads**: Update lead information and generate call notes
- **Send Emails**: Create Gmail drafts for selected leads with improved error handling
- **Configure Templates**: Customize email templates and business context
- **Session Management**: Proper caching and session handling for better performance

## Quick Start

1. **Install Poetry** (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. **Clone and install dependencies**:
```bash
cd ai-leads-v2
poetry install
```

3. **Install Playwright browsers**:
```bash
poetry run playwright install
```

4. **Set up configuration**:
   - Copy `local_settings_sample.py` to `local_settings.py`
   - Add your Google Sheets API credentials
   - Add your OpenAI API key
   - Add Gmail API credentials (optional, for Zoho)

5. **Run the Flask app**:
```bash
./run_flask.sh
```
   Or alternatively:
```bash
poetry run python flask_app.py
```

6. **Open your browser** to `http://localhost:8501`

## Configuration

### Required Setup

1. **Google Cloud Platform**:
   - Create a new project in GCP
   - Create a service account and download the credentials as JSON
   - Enable the following APIs:
     - [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
     - [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
     - [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) (for email drafts)

2. **OpenAI API**:
   - Get your API key from [OpenAI](https://platform.openai.com/api-keys)

3. **Update local_settings.py**:
   - Add your Google service account credentials
   - Add your OpenAI API key
   - Add Gmail user email for email drafting

## Key Advantages

- **No timeout issues**: Long-running operations work without interruption
- **Better error handling**: Improved classification of permanent vs transient errors
- **Faster performance**: Efficient caching and session management
- **Clean UI**: Responsive design that works on all devices
- **Real-time feedback**: AJAX operations with progress indicators

## Usage Flow

1. **Create or connect to a Google Sheet** with your lead data
2. **Generate searches** using AI to create targeted queries
3. **Run searches** to find potential leads
4. **Check sources** to extract contact information
5. **Check leads** to validate and add call notes
6. **Send emails** to create personalized Gmail drafts
7. **Configure templates** to customize your outreach

## Alternative: Streamlit App (Legacy)

If you prefer the Streamlit interface, you can still run it:

```bash
poetry run streamlit run main.py
```

**Note**: The Streamlit app may have timeout issues with long-running operations. The Flask app is recommended for production use.

## Troubleshooting

- **Permission errors**: Ensure your Google service account has access to your sheets
- **API rate limits**: The tool includes built-in rate limiting and retry logic
- **Memory issues**: Large datasets are processed in batches to prevent memory problems
- **Dead websites**: The tool now properly handles and marks permanently failed websites
