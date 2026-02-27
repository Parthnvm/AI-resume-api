#!/usr/bin/env python3
import os
from app import create_app

# Create the Flask application instance
app = create_app()

if __name__ == '__main__':
    # Ensure required directories exist for file uploads and results
    os.makedirs('resumes', exist_ok=True)
    os.makedirs('results', exist_ok=True)
    
    print("🚀 Starting Unified Resume Shortlister System...")
    print("👉 Access the portal at: http://localhost:5000")
    
    # Run a single unified server on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)