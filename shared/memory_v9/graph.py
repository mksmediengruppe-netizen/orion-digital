"""
Knowledge Graph — связи между фактами.
Не просто "nginx установлен", а: nginx → конфиг → /etc/nginx/... → сервер X → проект Y.
SQLite-based, без Neo4j.
"""
import sqlite3, json, os, threading, logging, re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.graph")
_local = threading.local()

def _conn():
    if not hasattr(_local, "c") or _local.c is None:
        os.makedirs(os.path.dirname(MemoryConfig.GRAPH_DB), exist_ok=True)
        _local.c = sqlite3.connect(MemoryConfig.GRAPH_DB, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, entity_type TEXT,
                user_id TEXT, metadata TEXT DEFAULT '{}',
                confidence REAL DEFAULT 0.8,
                created_at TEXT, updated_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_name ON entities(name, user_id);
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER REFERENCES entities(id),
                relation TEXT NOT NULL,
                object_id INTEGER REFERENCES entities(id),
                user_id TEXT, confidence REAL DEFAULT 0.8,
                source TEXT, created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rel_subj ON relations(subject_id);
            CREATE INDEX IF NOT EXISTS idx_rel_obj ON relations(object_id);
        """)
        _local.c.commit()
    return _local.c


class KnowledgeGraph:
    """Граф знаний: сущности + связи."""

    @staticmethod
    def add_entity(name: str, entity_type: str, user_id: str,
                   metadata: Dict = None, confidence: float = 0.8) -> int:
        try:
            c = _conn()
            now = datetime.now(timezone.utc).isoformat()
            row = c.execute("SELECT id FROM entities WHERE name=? AND user_id=?", (name, user_id)).fetchone()
            if row:
                c.execute("UPDATE entities SET updated_at=?, confidence=MAX(confidence,?) WHERE id=?",
                          (now, confidence, row["id"]))
                c.commit()
                return row["id"]
            c.execute("INSERT INTO entities (name,entity_type,user_id,metadata,confidence,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                      (name, entity_type, user_id, json.dumps(metadata or {}), confidence, now, now))
            c.commit()
            return c.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as e:
            logger.error(f"Graph add_entity: {e}"); return -1

    @staticmethod
    def add_relation(subject: str, relation: str, obj: str,
                     user_id: str, source: str = "auto",
                     confidence: float = 0.8):
        try:
            subj_id = KnowledgeGraph.add_entity(subject, "auto", user_id)
            obj_id = KnowledgeGraph.add_entity(obj, "auto", user_id)
            if subj_id < 0 or obj_id < 0: return
            c = _conn()
            c.execute("INSERT INTO relations (subject_id,relation,object_id,user_id,confidence,source,created_at) VALUES (?,?,?,?,?,?,?)",
                      (subj_id, relation, obj_id, user_id, confidence, source, datetime.now(timezone.utc).isoformat()))
            c.commit()
        except Exception as e:
            logger.error(f"Graph add_relation: {e}")

    @staticmethod
    def traverse(entity_name: str, user_id: str, max_hops: int = None) -> List[Dict]:
        """Обойти граф от сущности на N шагов."""
        max_hops = max_hops or MemoryConfig.GRAPH_MAX_HOPS
        try:
            c = _conn()
            results = []
            visited = set()
            queue = [(entity_name, 0)]
            while queue:
                name, depth = queue.pop(0)
                if depth > max_hops or name in visited: continue
                visited.add(name)
                row = c.execute("SELECT id FROM entities WHERE name=? AND user_id=?", (name, user_id)).fetchone()
                if not row: continue
                eid = row["id"]
                for rel in c.execute("SELECT r.relation, e.name as target, r.confidence FROM relations r JOIN entities e ON r.object_id=e.id WHERE r.subject_id=? AND r.user_id=?", (eid, user_id)):
                    results.append({"from": name, "relation": rel["relation"], "to": rel["target"], "confidence": rel["confidence"], "depth": depth})
                    queue.append((rel["target"], depth + 1))
                for rel in c.execute("SELECT r.relation, e.name as source, r.confidence FROM relations r JOIN entities e ON r.subject_id=e.id WHERE r.object_id=? AND r.user_id=?", (eid, user_id)):
                    results.append({"from": rel["source"], "relation": rel["relation"], "to": name, "confidence": rel["confidence"], "depth": depth})
                    queue.append((rel["source"], depth + 1))
            return results
        except Exception as e:
            logger.error(f"Graph traverse: {e}"); return []

    @staticmethod
    def get_context_for_prompt(query: str, user_id: str) -> str:
        """Извлечь граф-контекст для промпта."""
        words = [w for w in query.split() if len(w) > 3]
        all_rels = []
        for w in words[:5]:
            rels = KnowledgeGraph.traverse(w, user_id, max_hops=2)
            all_rels.extend(rels)
        if not all_rels: return ""
        seen = set()
        lines = ["ГРАФ ЗНАНИЙ:"]
        for r in all_rels:
            key = f"{r['from']}-{r['relation']}-{r['to']}"
            if key in seen: continue
            seen.add(key)
            lines.append(f"  {r['from']} → [{r['relation']}] → {r['to']}")
        return "\n".join(lines[:15])

    @staticmethod
    def extract_from_conversation(user_msg: str, assistant_resp: str,
                                  user_id: str, call_llm=None):
        """Извлечь сущности и связи из диалога."""
        if call_llm:
            try:
                resp = call_llm([
                    {"role": "system", "content": "Извлеки сущности и связи. JSON: [{\"s\":\"nginx\",\"r\":\"установлен_на\",\"o\":\"10.0.0.1\"}]. Только конкретные факты. Без markdown."},
                    {"role": "user", "content": f"User: {user_msg[:500]}\nAgent: {assistant_resp[:500]}"}
                ])
                resp = resp.strip()
                if resp.startswith("```"): resp = resp.split("\n",1)[1].rsplit("```",1)[0]
                triples = json.loads(resp)
                for t in triples:
                    if "s" in t and "r" in t and "o" in t:
                        KnowledgeGraph.add_relation(t["s"], t["r"], t["o"], user_id)
                return len(triples)
            except: pass
        # Fallback: regex
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', user_msg + " " + assistant_resp)
        for ip in set(ips):
            KnowledgeGraph.add_entity(ip, "server", user_id)
        domains = re.findall(r'(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,})', user_msg + " " + assistant_resp)
        for d in set(domains):
            KnowledgeGraph.add_entity(d, "domain", user_id)
        return 0
