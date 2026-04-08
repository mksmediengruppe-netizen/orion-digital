#!/usr/bin/env python3
"""
ARCANE 3.0 — Manus API Connection Test
=======================================
Runs BEFORE deploying to verify:
  1. Network connectivity (proxy or direct)
  2. API key format (JWT vs sk-)
  3. Authentication (valid token)

Usage:
  # Direct (will likely get 403 from Russia):
  python3 test_manus_connection.py

  # With proxy:
  MANUS_PROXY=http://user:pass@proxy:port python3 test_manus_connection.py

  # With custom key:
  MANUS_API_KEY=your_jwt_token python3 test_manus_connection.py
"""
import asyncio
import os
import sys

API_URL = os.environ.get("MANUS_API_URL", "https://api.manus.ai")
API_KEY = os.environ.get("MANUS_API_KEY", "")
PROXY   = os.environ.get("MANUS_PROXY", "")


async def test():
    try:
        import httpx
    except ImportError:
        print("❌ httpx not installed: pip install httpx")
        return

    print(f"Manus API URL : {API_URL}")
    print(f"API Key       : {API_KEY[:12]}... ({len(API_KEY)} chars)" if API_KEY else "API Key       : NOT SET")
    print(f"Proxy         : {PROXY[:40]}" if PROXY else "Proxy         : NONE (direct)")
    print()

    # Key format check
    if not API_KEY:
        print("⚠️  MANUS_API_KEY is not set")
    elif API_KEY.startswith("sk-"):
        print("⚠️  KEY FORMAT: 'sk-...' is OpenAI format — Manus expects JWT (header.payload.signature)")
        print("   Get JWT from: https://manus.ai/dashboard → Settings → API → Generate Token")
    elif API_KEY.count(".") == 2:
        print("✅ KEY FORMAT: looks like JWT (3 segments) — correct format")
    else:
        print(f"⚠️  KEY FORMAT: unknown ({API_KEY.count('.')} dots, {len(API_KEY)} chars)")

    # Auth header
    if API_KEY.count(".") == 2 and not API_KEY.startswith("sk-"):
        auth_header = {"Authorization": f"Bearer {API_KEY}"}
        print("   Auth: Authorization: Bearer <jwt>")
    else:
        auth_header = {"API_KEY": API_KEY}
        print("   Auth: API_KEY: <key> (fallback)")

    print()
    print("─" * 50)
    print("Testing connectivity...")

    client_kwargs = {"timeout": 15.0}
    if PROXY:
        client_kwargs["proxies"] = PROXY

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            # Test 1: Basic reachability (GET /)
            try:
                r = await client.get(API_URL, follow_redirects=True)
                print(f"GET {API_URL}  →  {r.status_code}")
            except Exception as e:
                print(f"GET {API_URL}  →  ERROR: {e}")

            # Test 2: API health/status (unauthenticated)
            for path in ["/health", "/v1/health", "/status", "/v1/status"]:
                try:
                    r = await client.get(f"{API_URL}{path}")
                    print(f"GET {path:20s}  →  {r.status_code} {r.text[:60]}")
                except Exception as e:
                    print(f"GET {path:20s}  →  {e}")

            # Test 3: Authenticated request
            if API_KEY:
                try:
                    r = await client.get(
                        f"{API_URL}/v1/tasks",
                        headers={**auth_header, "Accept": "application/json"},
                    )
                    print(f"GET /v1/tasks (auth)   →  {r.status_code} {r.text[:100]}")
                    if r.status_code == 200:
                        print("✅ AUTHENTICATION: SUCCESS")
                    elif r.status_code == 401:
                        print(f"❌ AUTHENTICATION: FAILED — {r.text[:200]}")
                    elif r.status_code == 403:
                        print("❌ GEO-BLOCK: 403 from AWS ELB — need proxy from non-RU IP")
                    elif r.status_code == 404:
                        print(f"⚠️  /v1/tasks not found — check API URL or endpoint path")
                except Exception as e:
                    print(f"GET /v1/tasks (auth)   →  {e}")

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        if PROXY:
            print(f"   Check proxy: {PROXY[:50]}")

    print()
    print("─" * 50)
    print("SUMMARY:")
    print("  To fix 403 (geo-block): set MANUS_PROXY=http://user:pass@us-proxy:port")
    print("  To fix 401 (bad key):   get JWT token from https://manus.ai/dashboard")
    print("  Both fixes go in /root/arcane2/.env:")
    print("    MANUS_PROXY=http://user:pass@proxy:port")
    print("    MANUS_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")


if __name__ == "__main__":
    asyncio.run(test())
