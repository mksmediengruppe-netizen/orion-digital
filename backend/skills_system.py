"""
ORION Skills System
====================
Modular agent capabilities that can be loaded, updated, and managed at runtime.
Each skill is a directory with SKILL.md (instructions), metadata, and optional scripts.
Skills extend the agent's functionality without code changes or restarts.
"""

import os
import json
import logging
import hashlib
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from flask import Flask, request, jsonify

logger = logging.getLogger("skills_system")

SKILLS_DIR = os.environ.get("SKILLS_DIR", "/var/www/orion/backend/skills")
os.makedirs(SKILLS_DIR, exist_ok=True)


class Skill:
    """Represents a single agent skill."""

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.metadata: Dict = {}
        self.instructions: str = ""
        self.tools: List[Dict] = []
        self.is_active: bool = True
        self.loaded_at: float = 0
        self._load()

    def _load(self):
        """Load skill from directory."""
        # Read SKILL.md
        skill_md = os.path.join(self.path, "SKILL.md")
        if os.path.exists(skill_md):
            with open(skill_md, "r", encoding="utf-8") as f:
                self.instructions = f.read()

        # Read metadata.json
        meta_path = os.path.join(self.path, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {
                "name": self.name,
                "description": self._extract_description(),
                "version": "1.0.0",
                "author": "ORION",
                "tags": [],
            }

        # Read tools.json (optional tool definitions)
        tools_path = os.path.join(self.path, "tools.json")
        if os.path.exists(tools_path):
            with open(tools_path, "r", encoding="utf-8") as f:
                self.tools = json.load(f)

        self.is_active = self.metadata.get("active", True)
        self.loaded_at = time.time()

    def _extract_description(self) -> str:
        """Extract description from first paragraph of SKILL.md."""
        lines = self.instructions.split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                return line[:200]
        return ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.metadata.get("description", ""),
            "version": self.metadata.get("version", "1.0.0"),
            "author": self.metadata.get("author", "ORION"),
            "tags": self.metadata.get("tags", []),
            "is_active": self.is_active,
            "has_tools": len(self.tools) > 0,
            "tools_count": len(self.tools),
            "instructions_length": len(self.instructions),
            "loaded_at": self.loaded_at,
            "files": self._list_files(),
        }

    def _list_files(self) -> List[str]:
        files = []
        for f in os.listdir(self.path):
            if not f.startswith("."):
                files.append(f)
        return files

    def get_context(self) -> str:
        """Get skill context for agent prompt injection."""
        if not self.is_active:
            return ""
        return f"<skill name=\"{self.name}\">\n{self.instructions}\n</skill>"


class SkillsManager:
    """Manages all agent skills."""

    def __init__(self, skills_dir: str = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills: Dict[str, Skill] = {}
        self._load_all()

    def _load_all(self):
        """Load all skills from the skills directory."""
        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir, exist_ok=True)
            return

        for name in os.listdir(self.skills_dir):
            path = os.path.join(self.skills_dir, name)
            if os.path.isdir(path) and os.path.exists(os.path.join(path, "SKILL.md")):
                try:
                    self._skills[name] = Skill(name, path)
                    logger.info(f"[SKILLS] Loaded: {name}")
                except Exception as e:
                    logger.warning(f"[SKILLS] Failed to load {name}: {e}")

        logger.info(f"[SKILLS] Total loaded: {len(self._skills)}")

    def reload(self):
        """Reload all skills."""
        self._skills.clear()
        self._load_all()

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self, active_only: bool = False) -> List[Dict]:
        skills = []
        for skill in self._skills.values():
            if active_only and not skill.is_active:
                continue
            skills.append(skill.to_dict())
        return skills

    def get_active_context(self) -> str:
        """Get combined context from all active skills for agent prompt."""
        contexts = []
        for skill in self._skills.values():
            ctx = skill.get_context()
            if ctx:
                contexts.append(ctx)
        if contexts:
            return "<skills>\n" + "\n".join(contexts) + "\n</skills>"
        return ""

    def get_active_tools(self) -> List[Dict]:
        """Get all tool definitions from active skills."""
        tools = []
        for skill in self._skills.values():
            if skill.is_active and skill.tools:
                tools.extend(skill.tools)
        return tools

    def create_skill(self, name: str, description: str, instructions: str,
                     tools: List[Dict] = None, metadata: Dict = None) -> Dict:
        """Create a new skill."""
        safe_name = name.lower().replace(" ", "-").replace("/", "-")
        skill_dir = os.path.join(self.skills_dir, safe_name)

        if os.path.exists(skill_dir):
            return {"success": False, "error": f"Skill '{safe_name}' already exists"}

        os.makedirs(skill_dir, exist_ok=True)

        # Write SKILL.md
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"# {name}\n\n{instructions}\n")

        # Write metadata.json
        meta = metadata or {}
        meta.update({
            "name": name,
            "description": description,
            "version": "1.0.0",
            "author": "ORION",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        with open(os.path.join(skill_dir, "metadata.json"), "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Write tools.json if provided
        if tools:
            with open(os.path.join(skill_dir, "tools.json"), "w") as f:
                json.dump(tools, f, indent=2)

        # Load the new skill
        self._skills[safe_name] = Skill(safe_name, skill_dir)

        return {"success": True, "name": safe_name, "path": skill_dir}

    def update_skill(self, name: str, updates: Dict) -> Dict:
        """Update an existing skill."""
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": "Skill not found"}

        if "instructions" in updates:
            with open(os.path.join(skill.path, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(updates["instructions"])

        if "metadata" in updates:
            meta_path = os.path.join(skill.path, "metadata.json")
            skill.metadata.update(updates["metadata"])
            with open(meta_path, "w") as f:
                json.dump(skill.metadata, f, indent=2, ensure_ascii=False)

        if "tools" in updates:
            with open(os.path.join(skill.path, "tools.json"), "w") as f:
                json.dump(updates["tools"], f, indent=2)

        if "active" in updates:
            skill.is_active = updates["active"]
            skill.metadata["active"] = updates["active"]

        # Reload skill
        skill._load()
        return {"success": True}

    def delete_skill(self, name: str) -> Dict:
        """Delete a skill."""
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": "Skill not found"}

        import shutil
        shutil.rmtree(skill.path, ignore_errors=True)
        del self._skills[name]
        return {"success": True}


# ── Singleton ──
_manager: Optional[SkillsManager] = None

def get_skills_manager() -> SkillsManager:
    global _manager
    if _manager is None:
        _manager = SkillsManager()
    return _manager


# ── Flask Routes ──

def register_skills_routes(app: Flask):
    """Register skills system API routes."""

    @app.route("/api/skills", methods=["GET"])
    def list_skills():
        mgr = get_skills_manager()
        active_only = request.args.get("active", "false").lower() == "true"
        skills = mgr.list_skills(active_only=active_only)
        return jsonify({"skills": skills, "count": len(skills)})

    @app.route("/api/skills/<name>", methods=["GET"])
    def get_skill(name):
        mgr = get_skills_manager()
        skill = mgr.get_skill(name)
        if not skill:
            return jsonify({"error": "Not found"}), 404
        result = skill.to_dict()
        result["instructions"] = skill.instructions
        return jsonify(result)

    @app.route("/api/skills", methods=["POST"])
    def create_skill():
        data = request.get_json() or {}
        name = data.get("name", "")
        if not name:
            return jsonify({"success": False, "error": "name required"}), 400

        mgr = get_skills_manager()
        result = mgr.create_skill(
            name=name,
            description=data.get("description", ""),
            instructions=data.get("instructions", ""),
            tools=data.get("tools"),
            metadata=data.get("metadata"),
        )
        return jsonify(result), 201 if result.get("success") else 400

    @app.route("/api/skills/<name>", methods=["PUT"])
    def update_skill(name):
        data = request.get_json() or {}
        mgr = get_skills_manager()
        result = mgr.update_skill(name, data)
        return jsonify(result)

    @app.route("/api/skills/<name>", methods=["DELETE"])
    def delete_skill(name):
        mgr = get_skills_manager()
        result = mgr.delete_skill(name)
        return jsonify(result)

    @app.route("/api/skills/reload", methods=["POST"])
    def reload_skills():
        mgr = get_skills_manager()
        mgr.reload()
        return jsonify({"reloaded": True, "count": len(mgr.list_skills())})

    logger.info("[SKILLS] Routes registered")
