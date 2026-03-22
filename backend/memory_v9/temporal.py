"""
Temporal Memory — снимки состояния сервера + diff.
"""
import json, os, logging, sqlite3, threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.temporal")
_local = threading.local()
_instance = None


def _conn():
    if not hasattr(_local, "c") or _local.c is None:
        db_path = os.path.join(MemoryConfig.DATA_DIR, "temporal.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _local.c = sqlite3.connect(db_path, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT, snapshot_data TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_snap_host ON snapshots(host);
        """)
        _local.c.commit()
    return _local.c


class TemporalMemory:
    def store_snapshot(self, host: str, data: Dict):
        try:
            c = _conn()
            c.execute("INSERT INTO snapshots (host,snapshot_data,created_at) VALUES (?,?,?)",
                      (host, json.dumps(data, ensure_ascii=False),
                       datetime.now(timezone.utc).isoformat()))
            c.commit()
        except Exception as e:
            logger.error(f"TemporalMemory store: {e}")

    def get_diff(self, host: str) -> str:
        try:
            c = _conn()
            rows = c.execute(
                "SELECT * FROM snapshots WHERE host=? ORDER BY id DESC LIMIT 2",
                (host,)
            ).fetchall()
            if len(rows) < 2:
                return "Недостаточно снимков для сравнения"
            new_data = json.loads(rows[0]["snapshot_data"])
            old_data = json.loads(rows[1]["snapshot_data"])
            diffs = []
            for key in new_data:
                if new_data.get(key) != old_data.get(key):
                    diffs.append(f"  {key}: {old_data.get(key,'?')} → {new_data.get(key,'?')}")
            return "\n".join(diffs) if diffs else "Изменений нет"
        except Exception as e:
            return f"Ошибка: {e}"


def get_temporal() -> TemporalMemory:
    global _instance
    if _instance is None:
        _instance = TemporalMemory()
    return _instance
