"""
ORION Digital v1.0 — Backend API Server
Автономный AI-инженер с мультиагентной системой, SSH executor,
browser agent, долговременной памятью, file versioning, rate limiting,
contracts validation, self-healing 2.0, LangGraph StateGraph.
v6.0: Creative Suite, Web Search, Memory & Projects, Canvas, Multi-Model Routing.
"""

import logging
logger = logging.getLogger(__name__)

import os
try:
    from dotenv import load_dotenv
    load_dotenv("/var/www/orion/backend/.env")
except ImportError:
    pass
import sys
import json
import time
import uuid
import hashlib
import bcrypt
# ══ SECURITY FIX 7: Fernet encryption for secrets in DB ══
from cryptography.fernet import Fernet

def _get_fernet():
    """Get Fernet instance. MUST have ORION_ENCRYPT_KEY set."""
    key = os.environ.get("ORION_ENCRYPT_KEY", "")
    if not key:
        raise RuntimeError(
            "ORION_ENCRYPT_KEY not set! Generate with: "
            "python3 -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
            "Add to .env: ORION_ENCRYPT_KEY=your_key"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


