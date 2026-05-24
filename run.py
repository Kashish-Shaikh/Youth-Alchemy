#!/usr/bin/env python3
"""
run.py — Youth Alchemy AI Skincare Platform — entry point
Usage:  python run.py
Then open: http://localhost:5000
"""
import os, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND  = os.path.join(BASE_DIR, 'backend')
sys.path.insert(0, BACKEND)
sys.path.insert(0, BASE_DIR)

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

from backend.app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
