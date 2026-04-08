"""
Temporal Memory — снимки состояния серверов + сравнение "что изменилось".
"""
import json, os, logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.temporal")

class TemporalMemory:
    def __init__(self):
        self._dir = MemoryConfig.SNAPSHOTS_DIR
        os.makedirs(self._dir, exist_ok=True)

    def save_snapshot(self, host: str, data: Dict, user_id: str = ""):
        """Сохранить снимок состояния сервера."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._dir, f"{host}_{ts}.json")
        snapshot = {"host": host, "user_id": user_id, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}
        try:
            with open(path, "w") as f: json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception as e: logger.error(f"Snapshot save: {e}")

    def get_latest(self, host: str) -> Optional[Dict]:
        try:
            files = sorted([f for f in os.listdir(self._dir) if f.startswith(host)], reverse=True)
            if files:
                with open(os.path.join(self._dir, files[0])) as f: return json.load(f)
        except: pass
        return None

    def get_diff(self, host: str) -> str:
        """Сравнить два последних снимка."""
        try:
            files = sorted([f for f in os.listdir(self._dir) if f.startswith(host)], reverse=True)
            if len(files) < 2: return "Нет данных для сравнения (нужно минимум 2 снимка)"
            with open(os.path.join(self._dir, files[0])) as f: new = json.load(f)
            with open(os.path.join(self._dir, files[1])) as f: old = json.load(f)
            changes = []
            nd, od = new.get("data",{}), old.get("data",{})
            for key in set(list(nd.keys()) + list(od.keys())):
                nv, ov = str(nd.get(key,"")), str(od.get(key,""))
                if nv != ov: changes.append(f"  {key}: {ov[:100]} → {nv[:100]}")
            if not changes: return f"Нет изменений между {old.get('timestamp','')} и {new.get('timestamp','')}"
            return f"ИЗМЕНЕНИЯ на {host} (с {old.get('timestamp','')} по {new.get('timestamp','')}):\n" + "\n".join(changes)
        except Exception as e: return f"Ошибка сравнения: {e}"

    def cleanup(self, host: str, keep: int = 50):
        """Оставить только последние N снимков."""
        try:
            files = sorted([f for f in os.listdir(self._dir) if f.startswith(host)])
            for f in files[:-keep]: os.remove(os.path.join(self._dir, f))
        except: pass

_temporal = None
def get_temporal() -> TemporalMemory:
    global _temporal
    if not _temporal: _temporal = TemporalMemory()
    return _temporal
