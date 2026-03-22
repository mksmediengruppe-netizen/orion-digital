"""
ORION Digital — File Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import re
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import uuid

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
    TEXT_EXTENSIONS, SKIP_EXTENSIONS, SKIP_DIRS,
)

from file_generator import (
    generate_file, get_file_info, get_file_path, list_files as list_generated_files,
    cleanup_old_files, GENERATED_DIR
)
from file_reader import read_file as read_any_file, FileReadResult, get_supported_formats
import mimetypes
import zipfile
import tarfile
import tempfile

file_bp = Blueprint("file", __name__)


def is_text_file(filename):
    name_lower = filename.lower()
    _, ext = os.path.splitext(name_lower)
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in SKIP_EXTENSIONS:
        return False
    basename = os.path.basename(name_lower)
    text_names = {
        'makefile', 'dockerfile', 'vagrantfile', 'gemfile', 'rakefile',
        'procfile', 'readme', 'license', 'changelog', 'authors',
    }
    return basename in text_names or not ext



def read_file_content(filepath, max_size=100000):
    try:
        size = os.path.getsize(filepath)
        if size > max_size:
            with open(filepath, 'r', errors='replace') as f:
                return f"[File too large: {size} bytes, first {max_size} bytes]\n" + f.read(max_size)
        with open(filepath, 'r', errors='replace') as f:
            content = f.read()
        if '\x00' in content[:1000]:
            return None
        return content
    except Exception:
        return None



def process_directory(dirpath, base_path=""):
    result = []
    file_count = 0
    max_files = 50
    max_total_chars = 200000
    total_chars = 0

    for root, dirs, files in os.walk(dirpath):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        dirs.sort()
        files.sort()

        for fname in files:
            if file_count >= max_files:
                result.append(f"\n... [{file_count}+ files, showing first {max_files}]")
                return result, file_count

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, dirpath)
            if base_path:
                rel_path = os.path.join(base_path, rel_path)

            if is_text_file(fname):
                content = read_file_content(fpath)
                if content is not None:
                    if total_chars + len(content) > max_total_chars:
                        remaining = max_total_chars - total_chars
                        if remaining > 500:
                            content = content[:remaining] + "\n... [truncated]"
                        else:
                            result.append(f"\n... [Content limit reached at {file_count} files]")
                            return result, file_count
                    _, ext = os.path.splitext(fname)
                    lang = ext.lstrip('.') if ext else 'text'
                    result.append(f"\n### File: `{rel_path}`\n```{lang}\n{content}\n```")
                    total_chars += len(content)
                    file_count += 1

    return result, file_count



def process_uploaded_file(file_storage):
    """Process uploaded file using UniversalFileReader for rich content extraction."""
    filename = file_storage.filename or "unknown"
    _, ext = os.path.splitext(filename.lower())

    tmp_dir = tempfile.mkdtemp(dir=UPLOAD_DIR)
    filepath = os.path.join(tmp_dir, filename)
    file_storage.save(filepath)

    # Store filepath for agent tools (read_any_file, analyze_image)
    file_id = str(uuid.uuid4())[:12]
    file_meta = {
        "id": file_id,
        "filename": filename,
        "filepath": filepath,
        "ext": ext,
        "size": os.path.getsize(filepath),
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }

    # Try UniversalFileReader for rich formats
    rich_formats = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
                    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg',
                    '.csv', '.json', '.xml', '.yaml', '.yml', '.md', '.html']

    if ext in rich_formats:
        try:
            result = read_any_file(filepath)
            if not result.error:
                content = result.text or ''
                tables = result.tables or []
                metadata = result.metadata or {}

                parts = [f"📄 **{filename}** ({result.file_type})"]
                if result.pages_count:
                    parts.append(f"**Страниц:** {result.pages_count}")
                if metadata:
                    meta_str = ", ".join(f"{k}: {v}" for k, v in list(metadata.items())[:5])
                    parts.append(f"**Метаданные:** {meta_str}")
                if tables:
                    parts.append(f"\n**Таблицы ({len(tables)}):**")
                    for i, tbl in enumerate(tables[:3]):
                        if isinstance(tbl, list):
                            # Table is list of rows
                            parts.append(f"\n*Таблица {i+1}:*\n{str(tbl)[:2000]}")
                        elif isinstance(tbl, dict):
                            parts.append(f"\n*Таблица {i+1}:*\n{tbl.get('markdown', tbl.get('text', str(tbl)))}")
                        else:
                            parts.append(f"\n*Таблица {i+1}:*\n{str(tbl)[:2000]}")
                if content:
                    if len(content) > 30000:
                        content = content[:30000] + f"\n... [обрезано, всего {len(content)} символов]"
                    parts.append(f"\n**Содержимое:**\n{content}")

                # Auto-summary: generate brief summary of file content
                summary = ""
                if content and len(content) > 100:
                    # Simple extractive summary: first 2 sentences
                    sentences = content.replace('\n', ' ').split('.')
                    summary = '. '.join(s.strip() for s in sentences[:3] if s.strip())
                    if summary:
                        summary = summary[:300] + ('...' if len(summary) > 300 else '')
                        parts.insert(1, f"**Краткое содержание:** {summary}")

                # Save file_meta for agent access
                file_meta['content_preview'] = content[:500] if content else ''
                file_meta['summary'] = summary
                file_meta['has_tables'] = len(tables) > 0
                _save_uploaded_file_meta(file_meta)

                return "\n".join(parts)
        except Exception as e:
            pass  # Fall through to legacy processing

    # Legacy: archives
    if ext == '.zip':
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                # ══ SECURITY FIX 5: Zip Slip protection ══
                for member in zf.namelist():
                    member_path = os.path.realpath(os.path.join(extract_dir, member))
                    if not member_path.startswith(os.path.realpath(extract_dir)):
                        raise ValueError(f"Zip Slip detected: {member}")
                zf.extractall(extract_dir)
            parts, count = process_directory(extract_dir, filename)
            return f"📦 **Архив: {filename}** ({count} файлов)\n" + "\n".join(parts)
        except Exception as e:
            return f"❌ Ошибка при распаковке {filename}: {str(e)}"

    elif ext in ('.tar', '.gz', '.tgz', '.bz2'):
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with tarfile.open(filepath, 'r:*') as tf:
                # ══ SECURITY FIX 5: Tar Slip protection ══
                for member in tf.getmembers():
                    member_path = os.path.realpath(os.path.join(extract_dir, member.name))
                    if not member_path.startswith(os.path.realpath(extract_dir)):
                        raise ValueError(f"Tar Slip detected: {member.name}")
                tf.extractall(extract_dir)
            parts, count = process_directory(extract_dir, filename)
            return f"📦 **Архив: {filename}** ({count} файлов)\n" + "\n".join(parts)
        except Exception as e:
            return f"❌ Ошибка при распаковке {filename}: {str(e)}"

    elif is_text_file(filename):
        content = read_file_content(filepath)
        if content:
            lang = ext.lstrip('.') if ext else 'text'
            _save_uploaded_file_meta(file_meta)
            return f"📄 **Файл: {filename}**\n```{lang}\n{content}\n```"
        return f"📄 **Файл: {filename}** [не удалось прочитать]"

    _save_uploaded_file_meta(file_meta)
    return f"📎 **Файл: {filename}** ({ext or 'unknown'} — бинарный файл, сохранён для анализа)\n[Путь: {filepath}]"


# ── Uploaded files metadata store ── PATCH 12 bug10: disk persistence ──
_UPLOAD_REGISTRY = os.path.join(UPLOAD_DIR, "_upload_registry.json")


def _load_upload_registry():
    """Load uploaded files registry from disk."""
    try:
        if os.path.exists(_UPLOAD_REGISTRY):
            with open(_UPLOAD_REGISTRY, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

_uploaded_files = _load_upload_registry()  # file_id -> file_meta, persisted to disk


def _save_uploaded_file_meta(meta):
    """Save uploaded file metadata for agent tool access (in-memory + disk)."""
    _uploaded_files[meta['id']] = meta
    try:
        with open(_UPLOAD_REGISTRY, 'w', encoding='utf-8') as f:
            json.dump(_uploaded_files, f, ensure_ascii=False)
    except Exception as _e:
        logging.warning(f"Upload registry save failed: {_e}")


def _get_uploaded_file_path(file_id):
    """Get filepath by file_id."""
    meta = _uploaded_files.get(file_id)
    return meta.get('filepath') if meta else None



@file_bp.route("/api/upload", methods=["POST"])
@file_bp.route("/api/files/upload", methods=["POST"])  # PATCH 12 bug4: alias for frontend compatibility
@require_auth
def upload_file():
    """Upload file(s) and return processed content with file paths for agent."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    files = request.files.getlist('file')
    results = []
    file_paths = []  # For agent tools
    for f in files:
        if f.filename:
            content = process_uploaded_file(f)
            results.append(content)
            # Find the saved filepath from _uploaded_files
            for fid, meta in sorted(_uploaded_files.items(), key=lambda x: x[1].get('uploaded_at', ''), reverse=True):
                if meta['filename'] == f.filename:
                    file_paths.append({"id": fid, "filename": meta['filename'], "filepath": meta['filepath'], "size": meta['size']})
                    break

    return jsonify({
        "content": "\n\n".join(results),
        "file_count": len(results),
        "files": file_paths
    })



@file_bp.route("/api/uploaded-files", methods=["GET"])
@require_auth
def list_uploaded_files():
    """List all uploaded files with metadata."""
    files = []
    for fid, meta in _uploaded_files.items():
        files.append({
            "id": fid,
            "filename": meta['filename'],
            "size": meta['size'],
            "ext": meta['ext'],
            "uploaded_at": meta['uploaded_at'],
            "has_tables": meta.get('has_tables', False)
        })
    return jsonify({"files": sorted(files, key=lambda x: x['uploaded_at'], reverse=True)})



@file_bp.route("/api/files/<file_id>/download", methods=["GET"])
def download_generated_file(file_id):
    """Download a generated file by ID. No auth required for direct download links."""
    filepath, filename = get_file_path(file_id)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'application/octet-stream'

    with open(filepath, 'rb') as f:
        data = f.read()

    return Response(
        data,
        mimetype=mime_type,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(len(data))
        }
    )



@file_bp.route("/api/files/<file_id>/preview", methods=["GET"])
def preview_generated_file(file_id):
    """Preview a generated file (HTML, images) in browser."""
    filepath, filename = get_file_path(file_id)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'text/plain'

    with open(filepath, 'rb') as f:
        data = f.read()

    return Response(
        data,
        mimetype=mime_type,
        headers={'Content-Disposition': f'inline; filename="{filename}"'}
    )



@file_bp.route("/api/files/<file_id>/info", methods=["GET"])
@require_auth
def file_info(file_id):
    """Get info about a generated file."""
    info = get_file_info(file_id)
    if not info:
        return jsonify({"error": "File not found"}), 404
    return jsonify(info)



@file_bp.route("/api/files", methods=["GET"])
@require_auth
def list_files_endpoint():
    """List generated files for current user."""
    chat_id = request.args.get("chat_id")
    limit = int(request.args.get("limit", 50))
    files = list_generated_files(chat_id=chat_id, user_id=request.user_id, limit=limit)
    return jsonify({"files": files, "total": len(files)})



@file_bp.route("/api/files/generate", methods=["POST"])
@require_auth
def generate_file_endpoint():
    """Generate a file on demand (from frontend)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    content = data.get("content", "")
    filename = data.get("filename", "file.txt")
    title = data.get("title")

    if not content:
        return jsonify({"error": "content is required"}), 400

    result = generate_file(
        content=content,
        filename=filename,
        title=title,
        chat_id=data.get("chat_id"),
        user_id=request.user_id
    )
    return jsonify(result)


# ── Export ─────────────────────────────────────────────────────────

@file_bp.route("/api/chats/<chat_id>/export", methods=["GET"])
@require_auth
def export_chat(chat_id):
    """Export chat as ZIP with all generated files."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat or (chat.get("user_id") != request.user_id and request.user.get("role") != "admin"):
        return jsonify({"error": "Chat not found"}), 404

    files = {}
    for msg in chat.get("messages", []):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            pattern = r'```(\w+)\s+([\w\-./]+\.\w+)\n(.*?)```'
            matches = re.findall(pattern, content, re.DOTALL)
            for lang, filename, code in matches:
                files[filename] = code

            if not matches:
                pattern2 = r'```(\w+)\n(.*?)```'
                matches2 = re.findall(pattern2, content, re.DOTALL)
                for i, (lang, code) in enumerate(matches2):
                    ext_map = {'html': '.html', 'css': '.css', 'javascript': '.js', 'js': '.js',
                               'python': '.py', 'py': '.py', 'json': '.json', 'sql': '.sql'}
                    ext = ext_map.get(lang, f'.{lang}')
                    files[f"file_{i+1}{ext}"] = code

    if not files:
        return jsonify({"error": "No code files found in chat"}), 404

    zip_path = os.path.join(UPLOAD_DIR, f"export_{chat_id}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            zf.writestr(fname, content)

    with open(zip_path, 'rb') as f:
        zip_data = f.read()

    os.remove(zip_path)

    return Response(
        zip_data,
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename=orion-{chat_id}.zip'}
    )


# ── Health Check ───────────────────────────────────────────────
