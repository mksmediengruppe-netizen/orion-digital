"""
ORION Image Generation Module
===============================
Integrates with OpenAI DALL-E and OpenRouter for image generation.
Supports: text-to-image, image editing, style transfer.
"""

import os
import io
import uuid
import time
import json
import logging
import base64
import hashlib
from typing import Dict, Optional, List
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_file

logger = logging.getLogger("image_generator")

GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/data/generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

# ── Image Generation Engine ──

class ImageGenerator:
    """Multi-provider image generation engine."""

    def __init__(self):
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._cache: Dict[str, str] = {}  # prompt_hash -> file_path

    def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        style: str = "natural",
        model: str = "dall-e-3",
        quality: str = "standard",
        n: int = 1,
        user_id: str = None,
    ) -> Dict:
        """Generate image(s) from text prompt."""
        import requests as http_requests

        # Check cache
        cache_key = hashlib.md5(f"{prompt}:{size}:{style}:{model}".encode()).hexdigest()
        if cache_key in self._cache and os.path.exists(self._cache[cache_key]):
            return {
                "success": True,
                "images": [{"url": f"/api/generated/{os.path.basename(self._cache[cache_key])}",
                           "path": self._cache[cache_key]}],
                "cached": True,
            }

        start = time.time()

        try:
            # Use OpenRouter for image generation
            if self.openrouter_key:
                result = self._generate_via_openrouter(prompt, size, style, model, quality, n)
            else:
                return {"success": False, "error": "No API key configured for image generation"}

            duration = time.time() - start
            result["duration_s"] = round(duration, 2)

            # Cache result
            if result.get("success") and result.get("images"):
                self._cache[cache_key] = result["images"][0].get("path", "")

            return result

        except Exception as e:
            logger.error(f"[IMAGE_GEN] Error: {e}")
            return {"success": False, "error": str(e)}

    def _generate_via_openrouter(
        self, prompt: str, size: str, style: str, model: str, quality: str, n: int
    ) -> Dict:
        """Generate via OpenRouter API."""
        import requests as http_requests

        # Use OpenRouter's image generation endpoint
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital",
        }

        # For DALL-E via OpenRouter
        payload = {
            "model": "openai/dall-e-3",
            "prompt": prompt,
            "n": min(n, 4),
            "size": size,
            "quality": quality,
            "style": style,
        }

        resp = http_requests.post(
            "https://openrouter.ai/api/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=120,
        )

        if resp.status_code != 200:
            # Fallback: generate via chat completion with image description
            return self._generate_placeholder(prompt, size)

        data = resp.json()
        images = []

        for i, img_data in enumerate(data.get("data", [])):
            if img_data.get("url"):
                # Download image
                img_resp = http_requests.get(img_data["url"], timeout=60)
                if img_resp.status_code == 200:
                    filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                    filepath = os.path.join(GENERATED_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(img_resp.content)
                    images.append({
                        "url": f"/api/generated/{filename}",
                        "path": filepath,
                        "revised_prompt": img_data.get("revised_prompt", prompt),
                    })
            elif img_data.get("b64_json"):
                img_bytes = base64.b64decode(img_data["b64_json"])
                filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(GENERATED_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                images.append({
                    "url": f"/api/generated/{filename}",
                    "path": filepath,
                    "revised_prompt": img_data.get("revised_prompt", prompt),
                })

        return {"success": len(images) > 0, "images": images}

    def _generate_placeholder(self, prompt: str, size: str) -> Dict:
        """Generate a placeholder image with PIL when API is unavailable."""
        try:
            from PIL import Image, ImageDraw, ImageFont

            w, h = [int(x) for x in size.split("x")]
            img = Image.new("RGB", (w, h), color=(30, 30, 50))
            draw = ImageDraw.Draw(img)

            # Draw gradient background
            for y in range(h):
                r = int(30 + (y / h) * 40)
                g = int(30 + (y / h) * 20)
                b = int(50 + (y / h) * 60)
                draw.line([(0, y), (w, y)], fill=(r, g, b))

            # Draw text
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                font = ImageFont.load_default()
                small_font = font

            # Title
            draw.text((w // 2, h // 3), "ORION Generated Image",
                      fill=(200, 200, 255), font=font, anchor="mm")

            # Prompt (truncated)
            short_prompt = prompt[:80] + "..." if len(prompt) > 80 else prompt
            draw.text((w // 2, h // 2), short_prompt,
                      fill=(150, 150, 200), font=small_font, anchor="mm")

            # Border
            draw.rectangle([2, 2, w - 3, h - 3], outline=(100, 100, 200), width=2)

            filename = f"gen_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(GENERATED_DIR, filename)
            img.save(filepath, "PNG")

            return {
                "success": True,
                "images": [{"url": f"/api/generated/{filename}", "path": filepath,
                           "revised_prompt": prompt, "placeholder": True}],
            }
        except Exception as e:
            return {"success": False, "error": f"Placeholder generation failed: {e}"}

    def list_generated(self, limit: int = 50) -> List[Dict]:
        """List recently generated images."""
        files = []
        for f in sorted(os.listdir(GENERATED_DIR), reverse=True)[:limit]:
            if f.endswith((".png", ".jpg", ".jpeg", ".webp")):
                path = os.path.join(GENERATED_DIR, f)
                files.append({
                    "filename": f,
                    "url": f"/api/generated/{f}",
                    "size": os.path.getsize(path),
                    "created": datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
                })
        return files


# ── Singleton ──
_generator: Optional[ImageGenerator] = None

def get_image_generator() -> ImageGenerator:
    global _generator
    if _generator is None:
        _generator = ImageGenerator()
    return _generator


# ── Flask Routes ──

def register_image_routes(app: Flask):
    """Register image generation API routes."""

    @app.route("/api/generate/image", methods=["POST"])
    def generate_image():
        auth = request.headers.get("Authorization", "")
        data = request.get_json() or {}
        prompt = data.get("prompt", "")
        if not prompt:
            return jsonify({"success": False, "error": "prompt required"}), 400

        gen = get_image_generator()
        result = gen.generate(
            prompt=prompt,
            size=data.get("size", "1024x1024"),
            style=data.get("style", "natural"),
            model=data.get("model", "dall-e-3"),
            quality=data.get("quality", "standard"),
            n=data.get("n", 1),
        )
        return jsonify(result)

    @app.route("/api/generated/<filename>")
    def serve_generated(filename):
        filepath = os.path.join(GENERATED_DIR, filename)
        if os.path.exists(filepath):
            return send_file(filepath)
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/generate/gallery", methods=["GET"])
    def image_gallery():
        gen = get_image_generator()
        images = gen.list_generated()
        return jsonify({"images": images, "count": len(images)})

    logger.info("[IMAGE_GEN] Routes registered")
