"""
ORION Backup Manager
=====================
Automatic backup system for SQLite databases and critical data.
Supports: scheduled backups, retention policies, restore, and status monitoring.
"""

import os
import shutil
import gzip
import json
import logging
import time
import sqlite3
import threading
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_file

logger = logging.getLogger("backup_manager")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)


class BackupManager:
    """Manages automatic backups of SQLite databases and critical files."""

    def __init__(self, data_dir: str = None, backup_dir: str = None):
        self.data_dir = data_dir or DATA_DIR
        self.backup_dir = backup_dir or BACKUP_DIR
        self.retention_days = 30
        self.max_backups = 100
        self._lock = threading.Lock()

    def _find_databases(self) -> List[str]:
        """Find all SQLite databases in data directory."""
        dbs = []
        for root, dirs, files in os.walk(self.data_dir):
            # Skip backup directory itself
            if "backups" in root:
                continue
            for f in files:
                if f.endswith((".db", ".sqlite", ".sqlite3")):
                    dbs.append(os.path.join(root, f))
        return dbs

    def create_backup(self, compress: bool = True, label: str = "") -> Dict:
        """Create a backup of all SQLite databases."""
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            if label:
                backup_name += f"_{label}"
            backup_path = os.path.join(self.backup_dir, backup_name)
            os.makedirs(backup_path, exist_ok=True)

            databases = self._find_databases()
            backed_up = []
            errors = []

            for db_path in databases:
                try:
                    db_name = os.path.basename(db_path)
                    dest = os.path.join(backup_path, db_name)

                    # Use SQLite online backup API for safe copy
                    src_conn = sqlite3.connect(db_path)
                    dst_conn = sqlite3.connect(dest)
                    src_conn.backup(dst_conn)
                    src_conn.close()
                    dst_conn.close()

                    # Compress if requested
                    if compress:
                        with open(dest, "rb") as f_in:
                            with gzip.open(f"{dest}.gz", "wb") as f_out:
                                shutil.copyfileobj(f_in, f_out)
                        os.remove(dest)
                        dest = f"{dest}.gz"

                    size = os.path.getsize(dest)
                    backed_up.append({
                        "database": db_name,
                        "source": db_path,
                        "backup": dest,
                        "size": size,
                        "compressed": compress,
                    })
                except Exception as e:
                    errors.append({"database": db_path, "error": str(e)})
                    logger.error(f"[BACKUP] Failed to backup {db_path}: {e}")

            # Save backup metadata
            meta = {
                "timestamp": timestamp,
                "label": label,
                "databases": backed_up,
                "errors": errors,
                "total_size": sum(b["size"] for b in backed_up),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(os.path.join(backup_path, "metadata.json"), "w") as f:
                json.dump(meta, f, indent=2)

            logger.info(f"[BACKUP] Created: {backup_name} ({len(backed_up)} databases)")

            return {
                "success": True,
                "backup_name": backup_name,
                "path": backup_path,
                "databases_backed_up": len(backed_up),
                "errors": len(errors),
                "total_size": meta["total_size"],
                "details": backed_up,
            }

    def list_backups(self) -> List[Dict]:
        """List all available backups."""
        backups = []
        if not os.path.exists(self.backup_dir):
            return backups

        for name in sorted(os.listdir(self.backup_dir), reverse=True):
            path = os.path.join(self.backup_dir, name)
            if not os.path.isdir(path):
                continue

            meta_path = os.path.join(path, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                backups.append({
                    "name": name,
                    "timestamp": meta.get("timestamp"),
                    "label": meta.get("label", ""),
                    "databases": len(meta.get("databases", [])),
                    "total_size": meta.get("total_size", 0),
                    "created_at": meta.get("created_at"),
                })
            else:
                # Legacy backup without metadata
                size = sum(
                    os.path.getsize(os.path.join(path, f))
                    for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f))
                )
                backups.append({
                    "name": name,
                    "total_size": size,
                    "created_at": datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
                })

        return backups

    def restore_backup(self, backup_name: str, database: str = None) -> Dict:
        """Restore databases from a backup."""
        backup_path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(backup_path):
            return {"success": False, "error": "Backup not found"}

        meta_path = os.path.join(backup_path, "metadata.json")
        if not os.path.exists(meta_path):
            return {"success": False, "error": "Backup metadata not found"}

        with open(meta_path) as f:
            meta = json.load(f)

        restored = []
        errors = []

        for db_info in meta.get("databases", []):
            db_name = db_info["database"]
            if database and db_name != database:
                continue

            try:
                backup_file = db_info["backup"]
                target = db_info["source"]

                if not os.path.exists(backup_file):
                    errors.append({"database": db_name, "error": "Backup file missing"})
                    continue

                # Create pre-restore backup
                if os.path.exists(target):
                    pre_restore = f"{target}.pre_restore_{int(time.time())}"
                    shutil.copy2(target, pre_restore)

                # Decompress if needed
                if backup_file.endswith(".gz"):
                    with gzip.open(backup_file, "rb") as f_in:
                        with open(target, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                else:
                    shutil.copy2(backup_file, target)

                restored.append({"database": db_name, "restored_to": target})
            except Exception as e:
                errors.append({"database": db_name, "error": str(e)})

        return {
            "success": len(restored) > 0,
            "restored": restored,
            "errors": errors,
        }

    def delete_backup(self, backup_name: str) -> Dict:
        """Delete a backup."""
        backup_path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(backup_path):
            return {"success": False, "error": "Backup not found"}
        shutil.rmtree(backup_path)
        return {"success": True}

    def cleanup_old_backups(self) -> Dict:
        """Remove backups older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = []

        for name in os.listdir(self.backup_dir):
            path = os.path.join(self.backup_dir, name)
            if not os.path.isdir(path):
                continue

            created = datetime.fromtimestamp(os.path.getctime(path))
            if created < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed.append(name)

        # Also enforce max_backups
        backups = sorted(
            [d for d in os.listdir(self.backup_dir) if os.path.isdir(os.path.join(self.backup_dir, d))],
            reverse=True,
        )
        while len(backups) > self.max_backups:
            old = backups.pop()
            shutil.rmtree(os.path.join(self.backup_dir, old), ignore_errors=True)
            removed.append(old)

        return {"removed": removed, "count": len(removed)}

    def get_status(self) -> Dict:
        """Get backup system status."""
        backups = self.list_backups()
        total_size = sum(b.get("total_size", 0) for b in backups)
        databases = self._find_databases()

        return {
            "total_backups": len(backups),
            "total_size": total_size,
            "total_size_human": self._human_size(total_size),
            "databases_tracked": len(databases),
            "database_files": [os.path.basename(d) for d in databases],
            "retention_days": self.retention_days,
            "max_backups": self.max_backups,
            "latest_backup": backups[0] if backups else None,
        }

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# ── Singleton ──
_manager: Optional[BackupManager] = None

def get_backup_manager() -> BackupManager:
    global _manager
    if _manager is None:
        _manager = BackupManager()
    return _manager


# ── Flask Routes ──

def register_backup_routes(app: Flask):
    """Register backup management API routes."""

    @app.route("/api/backups", methods=["GET"])
    def list_backups():
        mgr = get_backup_manager()
        backups = mgr.list_backups()
        return jsonify({"backups": backups, "count": len(backups)})

    @app.route("/api/backups", methods=["POST"])
    def create_backup():
        data = request.get_json() or {}
        mgr = get_backup_manager()
        result = mgr.create_backup(
            compress=data.get("compress", True),
            label=data.get("label", "manual"),
        )
        return jsonify(result)

    @app.route("/api/backups/status", methods=["GET"])
    def backup_status():
        mgr = get_backup_manager()
        return jsonify(mgr.get_status())

    @app.route("/api/backups/<name>/restore", methods=["POST"])
    def restore_backup(name):
        data = request.get_json() or {}
        mgr = get_backup_manager()
        result = mgr.restore_backup(name, database=data.get("database"))
        return jsonify(result)

    @app.route("/api/backups/<name>", methods=["DELETE"])
    def delete_backup(name):
        mgr = get_backup_manager()
        result = mgr.delete_backup(name)
        return jsonify(result)

    @app.route("/api/backups/cleanup", methods=["POST"])
    def cleanup_backups():
        mgr = get_backup_manager()
        result = mgr.cleanup_old_backups()
        return jsonify(result)

    logger.info("[BACKUP] Routes registered")
