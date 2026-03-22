"""
Knowledge Graph — связи между фактами.
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
    @staticmethod
    def add_entity(name: str, entity_type: str, user_id: str,
                   metadata: Dict = None, confidence: float = 0.8) -> int:
        try:
            c = _conn()
            now = datetime.now(timezone.utc).isoformat()
            row = c.execute("SELECT id FROM entities WHERE name=? AND user_id=?", (name, user_id)).fetchone()
            if row:
                c.execute("UPDATE entities SET updated_at=? WHERE id=?", (now, row["id"]))
                c.commit()
                return row["id"]
            c.execute("INSERT INTO entities (name,entity_type,user_id,metadata,confidence,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                      (name, entity_type, user_id, json.dumps(metadata or {}), confidence, now, now))
            c.commit()
            return c.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as e:
            logger.error(f"Graph add_entity: {e}")
            return -1

    @staticmethod
    def add_relation(subject: str, relation: str, obj: str,
                     user_id: str, source: str = "auto", confidence: float = 0.8):
        try:
            subj_id = KnowledgeGraph.add_entity(subject, "auto", user_id)
            obj_id = KnowledgeGraph.add_entity(obj, "auto", user_id)
            if subj_id < 0 or obj_id < 0:
                return
            c = _conn()
            c.execute("INSERT INTO relations (subject_id,relation,object_id,user_id,confidence,source,created_at) VALUES (?,?,?,?,?,?,?)",
                      (subj_id, relation, obj_id, user_id, confidence, source,
                       datetime.now(timezone.utc).isoformat()))
            c.commit()
        except Exception as e:
            logger.error(f"Graph add_relation: {e}")

    @staticmethod
    def get_context_for_prompt(query: str, user_id: str) -> str:
        words = [w for w in query.split() if len(w) > 3]
        if not words:
            return ""
        try:
            c = _conn()
            lines = ["ГРАФ ЗНАНИЙ:"]
            seen = set()
            for w in words[:5]:
                row = c.execute("SELECT id FROM entities WHERE name LIKE ? AND user_id=?",
                                (f"%{w}%", user_id)).fetchone()
                if not row:
                    continue
                eid = row["id"]
                rels = c.execute("""
                    SELECT r.relation, e.name as target FROM relations r
                    JOIN entities e ON r.object_id=e.id
                    WHERE r.subject_id=? AND r.user_id=? LIMIT 5
                """, (eid, user_id)).fetchall()
                for rel in rels:
                    key = f"{w}-{rel['relation']}-{rel['target']}"
                    if key not in seen:
                        seen.add(key)
                        lines.append(f"  {w} → [{rel['relation']}] → {rel['target']}")
            return "\n".join(lines) if len(lines) > 1 else ""
        except:
            return ""

    @staticmethod
    def extract_from_conversation(user_msg: str, assistant_resp: str,
                                  user_id: str, call_llm=None):
        if not call_llm:
            # Fallback: regex для IP и доменов
            ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                             user_msg + " " + assistant_resp)
            for ip in set(ips):
                KnowledgeGraph.add_entity(ip, "server", user_id)
            return 0
        try:
            resp = call_llm([
                {"role": "system", "content": 'Извлеки факты. JSON: [{"s":"nginx","r":"установлен_на","o":"10.0.0.1"}]. Только конкретные факты. Без markdown.'},
                {"role": "user", "content": f"User: {user_msg[:500]}\nAgent: {assistant_resp[:500]}"}
            ])
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
            triples = json.loads(resp)
            for t in triples:
                if "s" in t and "r" in t and "o" in t:
                    KnowledgeGraph.add_relation(t["s"], t["r"], t["o"], user_id)
            return len(triples)
        except:
            return 0
