"""
api/index.py — Vercel serverless entry point.

Vercel Note:
  - REST endpoints (/customers, /call/*, /twiml/*, /health) run as serverless functions.
  - The WebSocket endpoint (/media-stream/*) requires a persistent server.
    For live phone calls, run server.py on Railway/Render/Fly.io and point
    Twilio's Stream URL there. Use Vercel for the management UI + outbound triggers.
"""
import sys
import os

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import app  # noqa: F401 — Vercel picks up `app` from this module
