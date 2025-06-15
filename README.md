# Zakaya Lead Generation Tool

A streamlit-based tool for generating and managing leads for Zakaya, including automated email drafting capabilities.

## Features

- Search for potential leads using customizable queries
- Process and validate lead sources
- Generate automated email drafts using Zoho Mail
- Track lead status and email history
- Interactive web interface


## Installation

0. Setup GCP:
- Create a new project in GCP
- Create a service account and download the credentials as a JSON
    - No specific roles are required (i think) (but I used owner (i think))
- Enable the following APIs:
  - Google Sheets API - [link](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
  - Google Drive API - [link](https://console.cloud.google.com/apis/library/drive.googleapis.com)
  
  
1. Make sure you have Poetry installed:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Clone the repository and install dependencies:
```bash
cd ai-leads-v2
poetry lock
poetry install --no-root
```

3. Install Playwright browsers:
```bash
poetry run playwright install
```

## Usage

Run the Streamlit app:
```bash
poetry run streamlit run main.py
```

The app will open in your default web browser with the following features:

- **New Search**: Run new lead generation searches
- **Check Sources**: Process and validate lead sources
- **Expand Searches**: Generate new search queries based on history
- **Send Emails**: Create and manage email drafts

## Configuration

The tool requires the following configuration:
- Google Sheets API credentials
- Zoho Mail API credentials
- OpenAI API key

Replace the placeholder values in `local_settings_sample.py` with your own credentials.

Then, rename the file to `local_settings.py`. Zoho is optional but Google Sheets and OAI are required.

## Flask Web Application

A Flask-based web interface is now available as an alternative to the Streamlit app. The Flask app provides the same functionality with better performance and no timeout issues.

### Running the Flask App

1. Install dependencies using Poetry:
```bash
poetry install
```

2. Run the Flask app:
```bash
./run_flask.sh
# or
poetry run python flask_app.py
```

3. Open your browser to `http://localhost:5000`

See `README_FLASK.md` for more details about the Flask application.