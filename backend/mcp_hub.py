"""
MCP Hub — ORION Digital v1.0
============================
Model Context Protocol hub for external integrations.
OAuth management, connector registry, token storage.
"""

import os
import json
import time
import secrets
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("mcp_hub")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")


# ══════════════════════════════════════════════════════════════
# CONNECTOR REGISTRY
# ══════════════════════════════════════════════════════════════

class ConnectorRegistry:
    """Registry of available integration connectors."""

    CONNECTORS = {
        "github": {
            "name": "GitHub",
            "auth_type": "oauth",
            "oauth_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "scopes": ["repo", "read:user", "read:org"],
            "icon": "fab fa-github"
        },
        "gmail": {
            "name": "Gmail",
            "auth_type": "oauth",
            "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": ["gmail.readonly", "gmail.send"],
            "icon": "fas fa-envelope"
        },
        "google_calendar": {
            "name": "Google Calendar",
            "auth_type": "oauth",
            "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": ["calendar.readonly", "calendar.events"],
            "icon": "fas fa-calendar"
        },
        "google_drive": {
            "name": "Google Drive",
            "auth_type": "oauth",
            "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": ["drive.readonly", "drive.file"],
            "icon": "fab fa-google-drive"
        },
        "slack": {
            "name": "Slack",
            "auth_type": "oauth",
            "oauth_url": "https://slack.com/oauth/v2/authorize",
            "token_url": "https://slack.com/api/oauth.v2.access",
            "scopes": ["channels:read", "chat:write"],
            "icon": "fab fa-slack"
        },
        "notion": {
            "name": "Notion",
            "auth_type": "oauth",
            "oauth_url": "https://api.notion.com/v1/oauth/authorize",
            "token_url": "https://api.notion.com/v1/oauth/token",
            "scopes": ["read_content", "update_content"],
            "icon": "fas fa-book"
        },
        "jira": {
            "name": "Jira",
            "auth_type": "oauth",
            "oauth_url": "https://auth.atlassian.com/authorize",
            "token_url": "https://auth.atlassian.com/oauth/token",
            "scopes": ["read:jira-work", "write:jira-work"],
            "icon": "fab fa-jira"
        }
    }

    @classmethod
    def list_connectors(cls) -> List[Dict]:
        """List all available connectors."""
        return [
            {"id": k, **v}
            for k, v in cls.CONNECTORS.items()
        ]

    @classmethod
    def get_connector(cls, connector_id: str) -> Optional[Dict]:
        """Get connector config by ID."""
        config = cls.CONNECTORS.get(connector_id)
        if config:
            return {"id": connector_id, **config}
        return None


# ══════════════════════════════════════════════════════════════
# OAUTH TOKEN MANAGER
# ══════════════════════════════════════════════════════════════

class OAuthTokenManager:
    """Manages OAuth tokens for connected services."""

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or DATA_DIR
        self._tokens_file = os.path.join(self.data_dir, "oauth_tokens.json")
        self._tokens: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._tokens_file):
                with open(self._tokens_file, "r") as f:
                    self._tokens = json.load(f)
        except Exception:
            self._tokens = {}

    def _save(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self._tokens_file, "w") as f:
                json.dump(self._tokens, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")

    def store_token(self, user_id: str, connector_id: str, token_data: Dict) -> bool:
        """Store OAuth token for a user+connector pair."""
        key = f"{user_id}:{connector_id}"
        self._tokens[key] = {
            "connector_id": connector_id,
            "user_id": user_id,
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": token_data.get("expires_at", 0),
            "scopes": token_data.get("scopes", []),
            "connected_at": datetime.now(timezone.utc).isoformat()
        }
        self._save()
        return True

    def get_token(self, user_id: str, connector_id: str) -> Optional[Dict]:
        """Get stored token for a user+connector pair."""
        key = f"{user_id}:{connector_id}"
        return self._tokens.get(key)

    def revoke_token(self, user_id: str, connector_id: str) -> bool:
        """Revoke/disconnect a connector token."""
        key = f"{user_id}:{connector_id}"
        if key in self._tokens:
            del self._tokens[key]
            self._save()
            return True
        return False

    def list_connections(self, user_id: str) -> List[Dict]:
        """List all connected services for a user."""
        connections = []
        for key, token_data in self._tokens.items():
            if token_data.get("user_id") == user_id:
                connections.append({
                    "connector_id": token_data["connector_id"],
                    "connected_at": token_data.get("connected_at", ""),
                    "has_refresh_token": bool(token_data.get("refresh_token"))
                })
        return connections


# ══════════════════════════════════════════════════════════════
# MCP SERVER INTERFACE
# ══════════════════════════════════════════════════════════════

class MCPHub:
    """Central hub for MCP (Model Context Protocol) operations."""

    def __init__(self, data_dir: str = None):
        self.registry = ConnectorRegistry()
        self.token_manager = OAuthTokenManager(data_dir)
        self._mcp_servers: Dict[str, Dict] = {}

    def register_mcp_server(self, server_id: str, config: Dict):
        """Register an MCP server."""
        self._mcp_servers[server_id] = {
            "id": server_id,
            "name": config.get("name", server_id),
            "url": config.get("url", ""),
            "capabilities": config.get("capabilities", []),
            "registered_at": datetime.now(timezone.utc).isoformat()
        }

    def list_mcp_servers(self) -> List[Dict]:
        """List registered MCP servers."""
        return list(self._mcp_servers.values())

    def list_connectors(self) -> List[Dict]:
        """List all available connectors."""
        return ConnectorRegistry.list_connectors()

    def connect(self, user_id: str, connector_id: str, token_data: Dict) -> Dict:
        """Connect a user to a service."""
        connector = self.registry.get_connector(connector_id)
        if not connector:
            return {"success": False, "error": f"Unknown connector: {connector_id}"}

        self.token_manager.store_token(user_id, connector_id, token_data)
        return {"success": True, "connector": connector_id, "status": "connected"}

    def disconnect(self, user_id: str, connector_id: str) -> Dict:
        """Disconnect a user from a service."""
        revoked = self.token_manager.revoke_token(user_id, connector_id)
        return {"success": revoked, "connector": connector_id, "status": "disconnected"}

    def get_user_connections(self, user_id: str) -> List[Dict]:
        """Get all connections for a user."""
        return self.token_manager.list_connections(user_id)
