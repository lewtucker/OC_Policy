import sys
import os

# Add src/server to the path so server.py can import its siblings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'server'))

from server import app  # noqa: F401 — Vercel looks for `app`
