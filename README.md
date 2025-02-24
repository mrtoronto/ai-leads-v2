# Zakaya Lead Generation Tool

A streamlit-based tool for generating and managing leads for Zakaya, including automated email drafting capabilities.

## Features

- Search for potential leads using customizable queries
- Process and validate lead sources
- Generate automated email drafts using Zoho Mail
- Track lead status and email history
- Interactive web interface

## Installation

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