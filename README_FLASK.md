# Flask Lead Generation Tool - Detailed Documentation

This is the **primary application** for the Zakaya Lead Generation Tool. The Flask app provides all the functionality of the original Streamlit app with significant improvements in performance, reliability, and user experience.

## Why Flask Over Streamlit?

- **No timeout issues**: Long-running operations complete without interruption
- **Better error handling**: Improved classification of permanent vs transient website errors
- **Superior performance**: Faster page loads and data processing with intelligent caching
- **Robust session management**: Proper handling of user data and spreadsheet connections
- **Production-ready**: Built for reliability and scalability
- **Clean, responsive UI**: Works seamlessly on desktop and mobile devices

## Core Features

### 📊 **Sheet Management**
- Create new Google Sheets with proper lead tracking structure
- Connect to existing sheets with automatic validation
- Real-time cache management with manual refresh options

### 🔍 **Search Generation**
- AI-powered search query generation based on your search history
- Contextual search suggestions that improve over time
- Batch search processing for efficiency

### 🎯 **Lead Discovery**
- Execute single or multiple searches simultaneously
- Intelligent source processing to extract contact information
- Automated lead validation and deduplication

### 📞 **Lead Management**
- Update lead information with AI-generated call notes
- Validate contact details and website status
- Track lead status throughout the pipeline

### 📧 **Email Automation**
- Create personalized Gmail drafts with AI customization
- **Improved error handling**: Properly handles dead websites and permanent failures
- Template customization with business context integration
- Batch email processing with progress tracking

### ⚙️ **Configuration**
- Customize email templates for different lead types
- Configure business context for better personalization
- Template management with AI-powered improvements

## Installation & Setup

### Prerequisites

1. **Python 3.8+** with Poetry package manager
2. **Google Cloud Platform account** with required APIs enabled
3. **OpenAI API key** for AI-powered features
4. **Gmail account** for email draft creation

### Step-by-Step Setup

1. **Install Poetry** (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. **Clone and install dependencies**:
```bash
git clone <repository-url>
cd ai-leads-v2
poetry install
```

3. **Install Playwright browsers** (for web scraping):
```bash
poetry run playwright install
```

4. **Set up Google Cloud Platform**:
   - Create a new GCP project
   - Create a service account with JSON credentials
   - Enable these APIs:
     - [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
     - [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
     - [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)

5. **Configure credentials**:
   - Copy `local_settings_sample.py` to `local_settings.py`
   - Add your Google service account JSON credentials
   - Add your OpenAI API key
   - Add your Gmail user email

6. **Run the application**:
```bash
./run_flask.sh
```
   Or manually:
```bash
poetry run python flask_app.py
```

7. **Open your browser** to `http://localhost:8501`

## Application Architecture

### Backend Components
- **Flask application** (`flask_app.py`) - Main web server
- **Core modules** (`app/core/`) - Business logic and AI processing
- **Utilities** (`app/utils/`) - Google Sheets integration and caching
- **LLM integration** (`app/llm/`) - OpenAI integration for content generation

### Frontend Components
- **Responsive HTML templates** (`templates/`) - Clean, mobile-friendly UI
- **Vanilla JavaScript** (`static/js/`) - AJAX operations and interactivity
- **Minimal CSS** (`static/css/`) - Clean, professional styling

### Data Flow
1. **User input** → Flask routes → Core business logic
2. **AI processing** → OpenAI API → Structured data extraction
3. **Google Sheets** → Cached data layer → Real-time UI updates
4. **Email generation** → Gmail API → Draft creation

## Usage Guide

### Getting Started
1. **Enter your Google Sheet ID** on the home page
2. **Navigate using the sidebar** to access different features
3. **Monitor progress** with real-time feedback and status updates

### Workflow
1. **Create/Connect Sheet**: Set up your lead tracking spreadsheet
2. **Generate Searches**: Use AI to create targeted search queries
3. **Run Searches**: Execute searches to discover potential leads
4. **Check Sources**: Extract contact information from discovered sources
5. **Validate Leads**: Update and verify lead information
6. **Send Emails**: Create personalized Gmail drafts
7. **Track Progress**: Monitor your outreach efforts

### Advanced Features

#### Template Customization
- Customize email templates for different industries
- Use AI to improve your business context
- A/B test different messaging approaches

#### Batch Processing
- Process multiple searches simultaneously
- Handle large lead lists efficiently
- Automatic retry logic for transient failures

#### Error Handling
- **Permanent failures** (dead websites, DNS issues) are automatically marked as complete
- **Transient failures** (timeouts, rate limits) are retried appropriately
- **Detailed logging** for debugging and monitoring

## Troubleshooting

### Common Issues

**Permission Errors**
- Ensure your Google service account has access to your sheets
- Check that all required APIs are enabled in GCP

**Website Fetching Issues**
- The app now properly handles dead websites and DNS failures
- Permanent failures are marked as complete to avoid endless retries
- Check logs for detailed error information

**Memory Issues**
- Large datasets are processed in batches
- Restart the app if you encounter memory problems
- Consider upgrading your server resources for very large datasets

**API Rate Limits**
- Built-in rate limiting and retry logic
- Automatic backoff for temporary failures
- Monitor API usage in your respective dashboards

### Performance Optimization

- **Enable caching** for faster data access
- **Batch operations** when possible
- **Regular cache refresh** for updated data
- **Monitor resource usage** during large operations

## Development

### Running in Development Mode
```bash
poetry run flask run --debug
```

### Project Structure
```
ai-leads-v2/
├── flask_app.py              # Main Flask application
├── app/
│   ├── core/                 # Business logic modules
│   ├── utils/                # Utility functions
│   ├── llm/                  # AI integration
│   └── local_settings.py     # Configuration
├── templates/                # HTML templates
├── static/                   # CSS/JS assets
└── scripts/                  # Utility scripts
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues, questions, or feature requests, please check the troubleshooting section above or create an issue in the repository.