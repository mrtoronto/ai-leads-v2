#!/bin/bash

# Run the Flask app using Poetry
echo "Starting Flask Lead Generation Tool..."
echo "The app will be available at http://localhost:5000"
echo ""

# Set default secret key if not provided
export SECRET_KEY=${SECRET_KEY:-"dev-secret-key-change-in-production"}

# Run the Flask app
poetry run python flask_app.py 