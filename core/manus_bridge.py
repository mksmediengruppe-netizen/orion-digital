"""
ARCANE 3.0 — Manus Bridge
============================
Protocol for submitting task packages to Manus execution backend.

Manus is the ONLY agent with SSH and browser access.
Arcane = control plane. Manus = execution fabric.

Manus receives a package:
  - files (HTML/CSS/JS from Developer)
  - design_spec.json (from Art Director)
  - instructions (what to check, what to deploy)
  - mode (quality/balanced/economy)

Manus returns:
  - screenshots (desktop + mobile)
  - visual_issues (list of problems found)
  - deploy_url (if deployed)
  - lighthouse_score (performance)

Usage:
    bridge = ManusBridge(manus_api_url="https://api.manus.ai")
    result = await bridge.submit(package)
    # result.screenshots, result.deploy_url, result.visual_issues
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("arcane.manus_bridge")


class ManusMode(str, Enum):
    QUALITY = "quality"       # Full polish + detailed visual QA
    BALANCED = "balanced"     # Standard check + deploy
    ECONOMY = "economy"       # Quick check + deploy
    MOCK = "mock"             # Local-only, no real Manus (FREE mode)


@dataclass
class ManusPackage:
    """Package to submit to Manus for execution."""
    project_id: str
    task_description: str

    # Files to process
    files: dict[str, str] = field(default_factory=dict)       # {path: text content}
    binary_files: dict[str, bytes] = field(default_factory=dict)  # {path: binary bytes} for images
    assets: list[str] = field(default_factory=list)            # asset file paths

    # Design context
    design_spec: dict | None = None                            # from Art Director

    # Instructions
    instructions: list[str] = field(default_factory=list)      # what to check/do
    deploy_target: dict | None = None                          # {host, user, path, port}

    # Config
    mode: ManusMode = ManusMode.BALANCED
    check_mobile: bool = True
    check_desktop: bool = True
    run_lighthouse: bool = True
    auto_deploy: bool = True
    backup_before_deploy: bool = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "task": self.task_description,
            "files": self.files,
            "assets": self.assets,
            "design_spec": self.design_spec,
            "instructions": self.instructions,
            "deploy_target": self.deploy_target,
            "mode": self.mode.value,
            "checks": {
                "mobile": self.check_mobile,
                "desktop": self.check_desktop,
                "lighthouse": self.run_lighthouse,
            },
            "deploy": {
                "auto": self.auto_deploy,
                "backup": self.backup_before_deploy,
            },
        }


@dataclass
class ManusResult:
    """Result from Manus execution."""
    success: bool = False
    
    # Visual QA
    screenshots: dict[str, str] = field(default_factory=dict)  # {"desktop": path, "mobile": path}
    visual_issues: list[str] = field(default_factory=list)     # problems found
    lighthouse_score: int = 0                                   # 0-100
    
    # Deploy
    deploy_url: str = ""
    deploy_status: str = ""                                     # "deployed", "failed", "skipped"
    backup_path: str = ""
    
    # Metadata
    credits_used: int = 0
    duration_seconds: float = 0
    error: str = ""

    @property
    def has_visual_issues(self) -> bool:
        return len(self.visual_issues) > 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "screenshots": self.screenshots,
            "visual_issues": self.visual_issues,
            "lighthouse_score": self.lighthouse_score,
            "deploy_url": self.deploy_url,
            "deploy_status": self.deploy_status,
            "backup_path": self.backup_path,
            "credits_used": self.credits_used,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class ManusBridge:
    """
    Bridge between ARCANE control plane and Manus execution backend.
    
    Manus is the ONLY component with SSH and browser access.
    All server operations and visual QA go through this bridge.
    """

    def __init__(
        self,
        manus_api_url: str | None = None,
        api_key: str | None = None,
        workspace: str | None = None,
    ):
        self.api_url = manus_api_url or os.environ.get("MANUS_API_URL", "https://api.manus.ai")
        self.api_key = api_key or os.environ.get("MANUS_API_KEY", "")
        self.workspace = workspace or os.environ.get("ARCANE_WORKSPACE", "/root/workspace")

    async def submit(self, package: ManusPackage) -> ManusResult:
        """Submit a package to Manus for execution.
        
        In MOCK mode: returns simulated result (for FREE tier / testing).
        In real mode: calls Manus API (to be implemented when API is available).
        """
        start = time.time()
        
        if package.mode == ManusMode.MOCK or not self.api_url:
            result = await self._mock_execute(package)
        else:
            result = await self._api_execute(package)
        
        result.duration_seconds = time.time() - start
        
        logger.info(
            f"Manus [{package.mode.value}] project={package.project_id}: "
            f"success={result.success}, issues={len(result.visual_issues)}, "
            f"deploy={result.deploy_status}, {result.duration_seconds:.1f}s"
        )
        
        return result

    async def _mock_execute(self, package: ManusPackage) -> ManusResult:
        """Mock execution for FREE mode and testing.
        
        Does NOT deploy. Does NOT open browser.
        Returns simulated result based on file analysis.
        """
        issues = []
        
        # Basic file checks
        for path, content in package.files.items():
            if path.endswith(".html"):
                if "<!DOCTYPE" not in content:
                    issues.append(f"{path}: missing DOCTYPE")
                if 'viewport' not in content:
                    issues.append(f"{path}: missing viewport meta")
                if 'Lorem ipsum' in content:
                    issues.append(f"{path}: contains Lorem ipsum")
        
        return ManusResult(
            success=True,
            visual_issues=issues,
            deploy_status="skipped",
            screenshots={},
            lighthouse_score=0,  # can't measure without browser
            credits_used=0,
        )

    # ── Manus API profile mapping ───────────────────────────────────────────
    _MODE_TO_PROFILE = {
        ManusMode.QUALITY:  "manus-1.6-max",
        ManusMode.BALANCED: "manus-1.6",
        ManusMode.ECONOMY:  "manus-1.6-lite",
        ManusMode.MOCK:     "manus-1.6-lite",
    }

    async def _api_execute(self, package: ManusPackage) -> ManusResult:
        """Real Manus API execution.
        
        Flow:
          1. Upload files via POST /v1/files → presigned URL → PUT
          2. Create task via POST /v1/tasks with prompt + attachments
          3. Poll GET /v1/tasks/{task_id} until completed
          4. Return result with task_url and status
        
        FAIL-CLOSED: if API fails → ManusResult(success=False, error=...).
        Never returns fake success.
        """
        import httpx
        
        if not self.api_url or not self.api_key:
            return ManusResult(
                success=False,
                error="Manus API not configured: set MANUS_API_URL and MANUS_API_KEY",
                deploy_status="error",
            )
        
        headers = {
            "API_KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                # ── Step 1a: Upload TEXT files ─────────────────────────────
                file_ids = []
                for filepath, content in package.files.items():
                    try:
                        # Create file record
                        create_resp = await client.post(
                            f"{self.api_url}/v1/files",
                            headers=headers,
                            json={"filename": filepath},
                        )
                        if create_resp.status_code != 200:
                            logger.warning(f"Manus file create failed for {filepath}: {create_resp.status_code}")
                            continue
                        
                        file_data = create_resp.json()
                        upload_url = file_data.get("upload_url")
                        file_id = file_data.get("id")
                        
                        if upload_url:
                            # Upload content to presigned S3 URL
                            put_resp = await client.put(
                                upload_url,
                                content=content.encode("utf-8"),
                                headers={"Content-Type": "text/plain"},
                            )
                            if put_resp.status_code in (200, 201, 204):
                                file_ids.append(file_id)
                                logger.debug(f"Uploaded text {filepath} → {file_id}")
                            else:
                                logger.warning(f"S3 upload failed for {filepath}: {put_resp.status_code}")
                    except Exception as e:
                        logger.warning(f"File upload error {filepath}: {e}")
                
                # ── Step 1b: Upload BINARY files (images) ──────────────────
                # ARCANE v13: images must be uploaded as binary for Manus to render them
                _CT_MAP = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp",
                    ".gif": "image/gif", ".svg": "image/svg+xml",
                    ".ico": "image/x-icon",
                }
                for filepath, content_bytes in package.binary_files.items():
                    try:
                        create_resp = await client.post(
                            f"{self.api_url}/v1/files",
                            headers=headers,
                            json={"filename": filepath},
                        )
                        if create_resp.status_code != 200:
                            logger.warning(f"Manus binary create failed for {filepath}: {create_resp.status_code}")
                            continue
                        
                        file_data = create_resp.json()
                        upload_url = file_data.get("upload_url")
                        file_id = file_data.get("id")
                        
                        if upload_url:
                            # Determine content type from extension
                            ext = "." + filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
                            content_type = _CT_MAP.get(ext, "application/octet-stream")
                            
                            put_resp = await client.put(
                                upload_url,
                                content=content_bytes,
                                headers={"Content-Type": content_type},
                            )
                            if put_resp.status_code in (200, 201, 204):
                                file_ids.append(file_id)
                                logger.info(f"Uploaded binary {filepath} ({len(content_bytes)} bytes, {content_type}) → {file_id}")
                            else:
                                logger.warning(f"S3 binary upload failed for {filepath}: {put_resp.status_code}")
                    except Exception as e:
                        logger.warning(f"Binary upload error {filepath}: {e}")
                
                # ── Step 2: Build prompt ──────────────────────────────────
                prompt_parts = [
                    f"Task: {package.task_description}",
                    "",
                    "Instructions:",
                ]
                for instr in package.instructions:
                    prompt_parts.append(f"- {instr}")
                
                if package.design_spec:
                    prompt_parts.append(f"\nDesign specification:\n{json.dumps(package.design_spec, ensure_ascii=False, indent=2)}")
                
                if package.deploy_target:
                    dt = package.deploy_target
                    prompt_parts.append(f"\nDeploy target: {dt.get('user', 'root')}@{dt.get('host', '')}:{dt.get('path', '/var/www/html')}")
                    if package.backup_before_deploy:
                        prompt_parts.append("IMPORTANT: Create backup before deploying.")
                
                prompt = "\n".join(prompt_parts)
                
                # ── Step 3: Create task ───────────────────────────────────
                task_body = {
                    "prompt": prompt,
                    "agentProfile": self._MODE_TO_PROFILE.get(package.mode, "manus-1.6"),
                    "taskMode": "agent",
                }
                
                # Attach uploaded files
                if file_ids:
                    task_body["attachments"] = [
                        {"type": "file_id", "file_id": fid} for fid in file_ids
                    ]
                
                create_task_resp = await client.post(
                    f"{self.api_url}/v1/tasks",
                    headers=headers,
                    json=task_body,
                )
                
                if create_task_resp.status_code != 200:
                    return ManusResult(
                        success=False,
                        error=f"Manus task creation failed: HTTP {create_task_resp.status_code} — {create_task_resp.text[:300]}",
                        deploy_status="error",
                    )
                
                task_data = create_task_resp.json()
                task_id = task_data.get("task_id", "")
                task_url = task_data.get("task_url", "")
                
                logger.info(f"Manus task created: {task_id} → {task_url}")
                
                # ── Step 4: Poll for completion ───────────────────────────
                import asyncio
                max_polls = 120       # 120 × 5s = 10 minutes max
                poll_interval = 5.0
                
                for i in range(max_polls):
                    await asyncio.sleep(poll_interval)
                    
                    try:
                        status_resp = await client.get(
                            f"{self.api_url}/v1/tasks/{task_id}",
                            headers=headers,
                        )
                        if status_resp.status_code != 200:
                            continue
                        
                        status_data = status_resp.json()
                        task_status = status_data.get("status", "")
                        
                        if task_status in ("completed", "done", "finished"):
                            logger.info(f"Manus task {task_id} completed after {(i+1)*poll_interval:.0f}s")
                            return ManusResult(
                                success=True,
                                deploy_url=task_url,
                                deploy_status="deployed",
                                credits_used=status_data.get("credits_used", 0),
                            )
                        
                        if task_status in ("failed", "error", "cancelled"):
                            return ManusResult(
                                success=False,
                                error=f"Manus task {task_status}: {status_data.get('error', 'unknown')}",
                                deploy_status="failed",
                            )
                        
                        # Still running
                        if i % 6 == 0:  # log every 30s
                            logger.info(f"Manus task {task_id}: {task_status} ({(i+1)*poll_interval:.0f}s)")
                            
                    except Exception as e:
                        logger.warning(f"Poll error: {e}")
                
                # Timeout
                return ManusResult(
                    success=False,
                    error=f"Manus task {task_id} timed out after {max_polls * poll_interval:.0f}s",
                    deploy_status="timeout",
                )
                
        except httpx.ConnectError as e:
            return ManusResult(
                success=False,
                error=f"Cannot connect to Manus API at {self.api_url}: {e}",
                deploy_status="error",
            )
        except Exception as e:
            return ManusResult(
                success=False,
                error=f"Manus API error: {e}",
                deploy_status="error",
            )

    def build_package(
        self,
        project_id: str,
        task: str,
        project_dir: str | Path,
        design_spec: dict | None = None,
        deploy_target: dict | None = None,
        mode: str = "balanced",
    ) -> ManusPackage:
        """Build a ManusPackage from project directory.
        
        Reads files from src/, assets from assets/.
        """
        project_path = Path(project_dir)
        src_dir = project_path / "src"
        assets_dir = project_path / "assets"
        
        # Collect source files (BUG-6 FIX: check resolve() stays inside project)
        files = {}
        binary_files = {}  # ARCANE v13: binary files (images) for Manus attachments
        
        # Binary extensions — read as bytes, upload as binary
        _BINARY_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico"}
        _TEXT_EXT = {".html", ".css", ".js", ".json", ".xml", ".txt", ".md"}
        
        if src_dir.exists():
            for f in src_dir.rglob("*"):
                if not f.is_file():
                    continue
                # Security: resolve symlinks and verify inside project
                resolved = f.resolve()
                if not str(resolved).startswith(str(project_path.resolve())):
                    logger.warning(f"Symlink traversal blocked: {f} → {resolved}")
                    continue
                
                rel_path = str(f.relative_to(src_dir))
                suffix = f.suffix.lower()
                
                if suffix in _TEXT_EXT:
                    try:
                        files[rel_path] = resolved.read_text(encoding="utf-8", errors="replace")
                    except Exception as e:
                        logger.warning(f"Failed to read text {rel_path}: {e}")
                elif suffix in _BINARY_EXT:
                    try:
                        # Size limit: 5 MB per image (safety)
                        if resolved.stat().st_size > 5 * 1024 * 1024:
                            logger.warning(f"Skipping large binary {rel_path}: {resolved.stat().st_size} bytes")
                            continue
                        binary_files[rel_path] = resolved.read_bytes()
                        logger.debug(f"Loaded binary {rel_path}: {len(binary_files[rel_path])} bytes")
                    except Exception as e:
                        logger.warning(f"Failed to read binary {rel_path}: {e}")
        
        # Collect asset RELATIVE paths (BUG-7 FIX: no absolute paths)
        assets = []
        if assets_dir.exists():
            for f in assets_dir.rglob("*"):
                if f.is_file():
                    resolved = f.resolve()
                    if not str(resolved).startswith(str(project_path.resolve())):
                        logger.warning(f"Symlink traversal blocked: {f} → {resolved}")
                        continue
                    assets.append(str(f.relative_to(project_path)))
        
        # Default instructions
        instructions = [
            "Check desktop (1440px) and mobile (375px) rendering",
            "Verify no horizontal scroll on mobile",
            "Check all buttons and links are clickable",
            "Run Lighthouse performance audit",
        ]
        if deploy_target:
            instructions.append(f"Deploy to {deploy_target.get('host', 'server')}")
            instructions.append("Verify HTTP 200 after deploy")
            instructions.append("Backup before deploy")
        
        return ManusPackage(
            project_id=project_id,
            task_description=task,
            files=files,
            binary_files=binary_files,  # ARCANE v13: images for attachments
            assets=assets,
            design_spec=design_spec,
            instructions=instructions,
            deploy_target=deploy_target,
            mode=ManusMode(mode),
        )
