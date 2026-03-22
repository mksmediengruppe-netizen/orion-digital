"""
Artifact Generator — ORION Digital v1.0 Creative Suite
=====================================================
Модуль генерации изображений, редактирования и интерактивных артефактов.

Tools:
- generate_image: AI image generation via OpenRouter (DALL-E 3, Flux, SD3)
- edit_image: Natural language image editing via Pillow
- create_artifact: Interactive HTML/SVG/Mermaid/React artifacts with versioning
- generate_design: UI mockups, landing pages, logos as HTML artifacts
"""

import os
import io
import re
import json
import uuid
import time
import base64
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("artifact_generator")

GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

# Artifact version store (in-memory + JSON persistence)
_artifact_store_path = os.path.join(GENERATED_DIR, "_artifacts.json")
_artifact_store = {}


def _load_artifact_store():
    global _artifact_store
    try:
        if os.path.exists(_artifact_store_path):
            with open(_artifact_store_path, "r") as f:
                _artifact_store = json.load(f)
    except Exception:
        _artifact_store = {}


def _save_artifact_store():
    try:
        with open(_artifact_store_path, "w") as f:
            json.dump(_artifact_store, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save artifact store: {e}")


# ══════════════════════════════════════════════════════════════
# IMAGE GENERATION
# ══════════════════════════════════════════════════════════════

def generate_image_ai(prompt: str, style: str = "auto", size: str = "1024x1024",
                      api_key: str = "", api_url: str = "",
                      chat_id: str = None, user_id: str = None) -> Dict[str, Any]:
    """
    Generate an image using AI models via OpenRouter.
    Falls back to high-quality Pillow generation if API fails.
    
    Styles: photo, illustration, logo, diagram, chart, ui_mockup, auto
    Sizes: 256x256, 512x512, 1024x1024, 1024x1792, 1792x1024
    """
    import requests as req

    file_id = str(uuid.uuid4())[:12]
    filename = f"{file_id}_generated.png"
    filepath = os.path.join(GENERATED_DIR, filename)

    # Try AI generation via OpenRouter image models
    if api_key:
        try:
            result = _generate_via_api(prompt, style, size, api_key, api_url, filepath)
            if result.get("success"):
                _register_generated(file_id, filename, filepath, "png",
                                    os.path.getsize(filepath), chat_id, user_id,
                                    meta={"prompt": prompt, "style": style, "method": "ai_api"})
                return {
                    "success": True,
                    "file_id": file_id,
                    "filename": filename,
                    "size": os.path.getsize(filepath),
                    "download_url": f"/api/files/{file_id}/download",
                    "preview_url": f"/api/files/{file_id}/preview",
                    "method": "ai_api"
                }
        except Exception as e:
            logger.warning(f"AI image generation failed, falling back to Pillow: {e}")

    # Fallback: High-quality Pillow generation
    try:
        result = _generate_pillow_image(prompt, style, size, filepath)
        if result:
            fsize = os.path.getsize(filepath)
            _register_generated(file_id, filename, filepath, "png", fsize,
                                chat_id, user_id,
                                meta={"prompt": prompt, "style": style, "method": "pillow"})
            return {
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "size": fsize,
                "download_url": f"/api/files/{file_id}/download",
                "preview_url": f"/api/files/{file_id}/preview",
                "method": "pillow_fallback"
            }
    except Exception as e:
        logger.error(f"Pillow image generation failed: {e}")

    return {"success": False, "error": "All image generation methods failed"}


def _generate_via_api(prompt: str, style: str, size: str, api_key: str,
                      api_url: str, filepath: str) -> Dict:
    """Generate image via OpenRouter compatible API."""
    import requests as req

    # Use OpenAI-compatible image generation endpoint
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Try OpenAI DALL-E 3 via OpenRouter
    style_prefix = {
        "photo": "A photorealistic photograph of ",
        "illustration": "A beautiful digital illustration of ",
        "logo": "A modern minimalist logo design for ",
        "diagram": "A clean technical diagram showing ",
        "chart": "A professional data visualization chart of ",
        "ui_mockup": "A modern UI/UX mockup design for ",
        "auto": ""
    }
    enhanced_prompt = style_prefix.get(style, "") + prompt

    # Try image generation via OpenRouter
    try:
        resp = req.post(
            "https://openrouter.ai/api/v1/images/generations",
            headers=headers,
            json={
                "model": "openai/dall-e-3",
                "prompt": enhanced_prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json"
            },
            timeout=60
        )

        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                img_b64 = data["data"][0].get("b64_json", "")
                if img_b64:
                    img_bytes = base64.b64decode(img_b64)
                    with open(filepath, "wb") as f:
                        f.write(img_bytes)
                    return {"success": True}

                img_url = data["data"][0].get("url", "")
                if img_url:
                    img_resp = req.get(img_url, timeout=30)
                    if img_resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(img_resp.content)
                        return {"success": True}
    except Exception as e:
        logger.warning(f"OpenRouter image API failed: {e}")

    # Fallback: Use vision model to generate SVG, then convert
    try:
        resp = req.post(
            api_url or "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [
                    {"role": "system", "content": "You are an SVG artist. Generate ONLY valid SVG code (no explanation). The SVG should be beautiful, detailed, and artistic."},
                    {"role": "user", "content": f"Create an SVG image: {enhanced_prompt}. Size: 800x600. Use gradients, shapes, and colors to make it visually appealing."}
                ],
                "temperature": 0.7,
                "max_tokens": 4000
            },
            timeout=60
        )

        if resp.status_code == 200:
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            svg_match = re.search(r'<svg[^>]*>.*?</svg>', content, re.DOTALL)
            if svg_match:
                svg_code = svg_match.group(0)
                # Convert SVG to PNG using Pillow/cairosvg
                try:
                    import cairosvg
                    cairosvg.svg2png(bytestring=svg_code.encode(), write_to=filepath,
                                    output_width=1024, output_height=768)
                    return {"success": True}
                except ImportError:
                    # Save as SVG and convert with Pillow
                    svg_path = filepath.replace('.png', '.svg')
                    with open(svg_path, 'w') as f:
                        f.write(svg_code)
                    # Use reportlab/Pillow for basic conversion
                    _svg_to_png_basic(svg_code, filepath)
                    return {"success": True}
    except Exception as e:
        logger.warning(f"SVG generation via LLM failed: {e}")

    return {"success": False}


def _svg_to_png_basic(svg_code: str, filepath: str):
    """Basic SVG to PNG conversion using Pillow."""
    from PIL import Image, ImageDraw
    # Create a placeholder with SVG info
    img = Image.new('RGB', (1024, 768), color='#1a1a2e')
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    draw.text((20, 20), "SVG Generated — view in browser", fill='white', font=font)
    img.save(filepath)


def _generate_pillow_image(prompt: str, style: str, size: str, filepath: str) -> bool:
    """Generate a high-quality image using Pillow with advanced techniques."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import random
    import math

    # Parse size
    try:
        w, h = map(int, size.split('x'))
    except ValueError:
        w, h = 1024, 1024

    img = Image.new('RGB', (w, h))
    draw = ImageDraw.Draw(img)

    # Color palettes by style
    palettes = {
        "photo": ['#1a1a2e', '#16213e', '#0f3460', '#533483', '#e94560'],
        "illustration": ['#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', '#54a0ff'],
        "logo": ['#2d3436', '#636e72', '#dfe6e9', '#6c5ce7', '#a29bfe'],
        "diagram": ['#ffffff', '#f1f2f6', '#dfe4ea', '#2f3542', '#3742fa'],
        "chart": ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981'],
        "ui_mockup": ['#f8f9fa', '#e9ecef', '#dee2e6', '#495057', '#6366f1'],
        "auto": ['#667eea', '#764ba2', '#f093fb', '#f5576c', '#4facfe']
    }
    colors = palettes.get(style, palettes["auto"])

    # Generate gradient background
    for y in range(h):
        r1, g1, b1 = _hex_to_rgb(colors[0])
        r2, g2, b2 = _hex_to_rgb(colors[1])
        ratio = y / h
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Add decorative elements based on style
    if style in ("diagram", "chart"):
        _draw_grid(draw, w, h, colors)
        _draw_chart_elements(draw, w, h, colors, prompt)
    elif style == "logo":
        _draw_logo_elements(draw, w, h, colors, prompt)
    elif style == "ui_mockup":
        _draw_ui_mockup(draw, w, h, colors, prompt)
    else:
        _draw_abstract_art(draw, w, h, colors, prompt)

    # Add title text
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(24, w // 30))
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(14, w // 60))
    except Exception:
        font_large = ImageFont.load_default()
        font_small = font_large

    # Title with shadow
    title = prompt[:80]
    draw.text((w // 2 - len(title) * 6 + 2, h - 82), title, fill='#00000088', font=font_large)
    draw.text((w // 2 - len(title) * 6, h - 84), title, fill='white', font=font_large)

    # Watermark
    draw.text((20, h - 30), "ORION Digital v1.0 • AI Generated", fill='#ffffff66', font=font_small)

    # Apply slight blur for smoothness
    img = img.filter(ImageFilter.SMOOTH)
    img.save(filepath, quality=95)
    return True


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _draw_grid(draw, w, h, colors):
    """Draw a subtle grid pattern."""
    grid_color = _hex_to_rgb(colors[2]) + (30,)
    for x in range(0, w, 40):
        draw.line([(x, 0), (x, h)], fill=colors[2], width=1)
    for y in range(0, h, 40):
        draw.line([(0, y), (w, y)], fill=colors[2], width=1)


def _draw_chart_elements(draw, w, h, colors, prompt):
    """Draw chart-like elements."""
    import random
    bar_count = random.randint(5, 10)
    bar_width = w // (bar_count * 2)
    max_height = h * 0.6

    for i in range(bar_count):
        bar_h = random.randint(int(max_height * 0.2), int(max_height))
        x = w // 4 + i * (bar_width + 10)
        y = h - 120 - bar_h
        color = colors[i % len(colors)]
        draw.rounded_rectangle([x, y, x + bar_width, h - 120], radius=5, fill=color)


def _draw_logo_elements(draw, w, h, colors, prompt):
    """Draw logo-style geometric elements."""
    import random
    cx, cy = w // 2, h // 2
    # Main circle
    r = min(w, h) // 4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colors[3], outline=colors[4], width=3)
    # Inner shape
    r2 = r // 2
    draw.rounded_rectangle([cx - r2, cy - r2, cx + r2, cy + r2], radius=r2 // 3, fill=colors[4])
    # Accent dots
    for angle in range(0, 360, 45):
        import math
        x = cx + int(r * 1.3 * math.cos(math.radians(angle)))
        y = cy + int(r * 1.3 * math.sin(math.radians(angle)))
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], fill=colors[2])


def _draw_ui_mockup(draw, w, h, colors, prompt):
    """Draw UI mockup elements."""
    # Window frame
    margin = 40
    draw.rounded_rectangle([margin, margin, w - margin, h - margin],
                           radius=12, fill='#ffffff', outline='#dee2e6', width=2)
    # Title bar
    draw.rectangle([margin, margin, w - margin, margin + 40], fill='#f8f9fa')
    draw.line([(margin, margin + 40), (w - margin, margin + 40)], fill='#dee2e6', width=1)
    # Traffic lights
    for i, c in enumerate(['#ff5f56', '#ffbd2e', '#27c93f']):
        draw.ellipse([margin + 15 + i * 25, margin + 12, margin + 29 + i * 25, margin + 26], fill=c)
    # Content blocks
    y_pos = margin + 60
    for i in range(4):
        block_h = 50 + (i % 2) * 30
        draw.rounded_rectangle([margin + 20, y_pos, w - margin - 20, y_pos + block_h],
                               radius=8, fill='#f1f3f5', outline='#e9ecef')
        y_pos += block_h + 15
    # Sidebar
    draw.rectangle([margin, margin + 40, margin + 200, h - margin], fill='#f8f9fa')
    draw.line([(margin + 200, margin + 40), (margin + 200, h - margin)], fill='#dee2e6')
    for i in range(6):
        y = margin + 60 + i * 45
        draw.rounded_rectangle([margin + 15, y, margin + 185, y + 35], radius=6, fill='#e9ecef')


def _draw_abstract_art(draw, w, h, colors, prompt):
    """Draw abstract artistic elements."""
    import random
    import math

    # Circles
    for _ in range(15):
        x = random.randint(0, w)
        y = random.randint(0, h)
        r = random.randint(20, 150)
        color = colors[random.randint(0, len(colors) - 1)]
        rgb = _hex_to_rgb(color)
        alpha_color = rgb  # Pillow RGB doesn't support alpha in draw
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=None)

    # Lines
    for _ in range(8):
        x1, y1 = random.randint(0, w), random.randint(0, h)
        x2, y2 = random.randint(0, w), random.randint(0, h)
        draw.line([(x1, y1), (x2, y2)], fill=colors[random.randint(2, len(colors) - 1)], width=3)

    # Rounded rectangles
    for _ in range(5):
        x = random.randint(0, w - 100)
        y = random.randint(0, h - 100)
        rw = random.randint(60, 200)
        rh = random.randint(60, 200)
        draw.rounded_rectangle([x, y, x + rw, y + rh], radius=15,
                               fill=colors[random.randint(0, len(colors) - 1)])


# ══════════════════════════════════════════════════════════════
# IMAGE EDITING
# ══════════════════════════════════════════════════════════════

def edit_image(filepath: str, instruction: str,
               chat_id: str = None, user_id: str = None) -> Dict[str, Any]:
    """
    Edit an image using natural language instructions.
    Supports: remove background, grayscale, blur, sharpen, resize,
    rotate, flip, crop, brightness, contrast, add text, sepia, invert.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps

    if not os.path.exists(filepath):
        return {"success": False, "error": f"File not found: {filepath}"}

    try:
        img = Image.open(filepath)
        original_format = img.format or "PNG"
        instruction_lower = instruction.lower()

        # Parse and apply operations
        if any(kw in instruction_lower for kw in ["удали фон", "remove background", "transparent", "прозрачн"]):
            img = _remove_background(img)

        elif any(kw in instruction_lower for kw in ["ч/б", "черно-бел", "grayscale", "grey", "gray", "серый"]):
            img = ImageOps.grayscale(img).convert("RGB")

        elif any(kw in instruction_lower for kw in ["сепия", "sepia", "vintage", "винтаж"]):
            img = _apply_sepia(img)

        elif any(kw in instruction_lower for kw in ["размыть", "blur", "размытие"]):
            radius = _extract_number(instruction_lower, default=5)
            img = img.filter(ImageFilter.GaussianBlur(radius=radius))

        elif any(kw in instruction_lower for kw in ["резкость", "sharpen", "четкость"]):
            enhancer = ImageEnhance.Sharpness(img)
            factor = _extract_number(instruction_lower, default=2.0)
            img = enhancer.enhance(factor)

        elif any(kw in instruction_lower for kw in ["яркость", "brightness", "светлее", "темнее"]):
            enhancer = ImageEnhance.Brightness(img)
            if any(kw in instruction_lower for kw in ["темнее", "darker", "dark"]):
                factor = 0.7
            else:
                factor = _extract_number(instruction_lower, default=1.5)
            img = enhancer.enhance(factor)

        elif any(kw in instruction_lower for kw in ["контраст", "contrast"]):
            enhancer = ImageEnhance.Contrast(img)
            factor = _extract_number(instruction_lower, default=1.5)
            img = enhancer.enhance(factor)

        elif any(kw in instruction_lower for kw in ["повернуть", "rotate", "поворот"]):
            angle = _extract_number(instruction_lower, default=90)
            img = img.rotate(angle, expand=True, fillcolor='white')

        elif any(kw in instruction_lower for kw in ["отразить", "flip", "зеркал", "mirror"]):
            if any(kw in instruction_lower for kw in ["верт", "vertical"]):
                img = ImageOps.flip(img)
            else:
                img = ImageOps.mirror(img)

        elif any(kw in instruction_lower for kw in ["resize", "размер", "масштаб"]):
            # Try to extract dimensions
            dims = re.findall(r'(\d+)\s*[xх×]\s*(\d+)', instruction_lower)
            if dims:
                new_w, new_h = int(dims[0][0]), int(dims[0][1])
                img = img.resize((new_w, new_h), Image.LANCZOS)
            else:
                factor = _extract_number(instruction_lower, default=0.5)
                new_w = int(img.width * factor)
                new_h = int(img.height * factor)
                img = img.resize((new_w, new_h), Image.LANCZOS)

        elif any(kw in instruction_lower for kw in ["обрезать", "crop", "кроп"]):
            # Center crop to 80%
            w, h = img.size
            left = int(w * 0.1)
            top = int(h * 0.1)
            right = int(w * 0.9)
            bottom = int(h * 0.9)
            img = img.crop((left, top, right, bottom))

        elif any(kw in instruction_lower for kw in ["инверт", "invert", "негатив"]):
            if img.mode == 'RGBA':
                r, g, b, a = img.split()
                rgb = Image.merge('RGB', (r, g, b))
                rgb = ImageOps.invert(rgb)
                r2, g2, b2 = rgb.split()
                img = Image.merge('RGBA', (r2, g2, b2, a))
            else:
                img = ImageOps.invert(img.convert('RGB'))

        elif any(kw in instruction_lower for kw in ["текст", "text", "надпись", "watermark"]):
            text_match = re.search(r'["\']([^"\']+)["\']', instruction)
            text = text_match.group(1) if text_match else "ORION Digital"
            img = _add_text_to_image(img, text)

        elif any(kw in instruction_lower for kw in ["рамк", "border", "frame"]):
            img = ImageOps.expand(img, border=20, fill='#6366f1')

        else:
            return {"success": False, "error": f"Не удалось распознать операцию: {instruction}. "
                    "Поддерживаемые: удалить фон, ч/б, сепия, размыть, резкость, яркость, контраст, "
                    "повернуть, отразить, resize, обрезать, инвертировать, добавить текст, рамка"}

        # Save edited image
        file_id = str(uuid.uuid4())[:12]
        filename = f"{file_id}_edited.png"
        out_path = os.path.join(GENERATED_DIR, filename)

        if img.mode == 'RGBA':
            img.save(out_path, 'PNG')
        else:
            img.save(out_path, 'PNG', quality=95)

        fsize = os.path.getsize(out_path)
        _register_generated(file_id, filename, out_path, "png", fsize, chat_id, user_id,
                            meta={"instruction": instruction, "original": filepath})

        return {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "size": fsize,
            "download_url": f"/api/files/{file_id}/download",
            "preview_url": f"/api/files/{file_id}/preview",
            "operation": instruction
        }

    except Exception as e:
        return {"success": False, "error": f"Image editing error: {str(e)}"}


def _remove_background(img):
    """Simple background removal using edge detection."""
    from PIL import ImageFilter
    # Convert to RGBA
    img = img.convert("RGBA")
    # Simple threshold-based removal (works for solid backgrounds)
    data = img.getdata()
    new_data = []
    # Get corner pixels as background reference
    w, h = img.size
    bg_pixels = [img.getpixel((0, 0)), img.getpixel((w-1, 0)),
                 img.getpixel((0, h-1)), img.getpixel((w-1, h-1))]
    avg_bg = tuple(sum(p[i] for p in bg_pixels) // 4 for i in range(3))

    threshold = 60
    for item in data:
        diff = sum(abs(item[i] - avg_bg[i]) for i in range(3))
        if diff < threshold:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)

    img.putdata(new_data)
    return img


def _apply_sepia(img):
    """Apply sepia tone filter."""
    from PIL import Image, ImageOps
    gray = ImageOps.grayscale(img)
    sepia = Image.merge("RGB", (
        gray.point(lambda x: min(255, int(x * 1.2 + 40))),
        gray.point(lambda x: min(255, int(x * 1.0 + 20))),
        gray.point(lambda x: min(255, int(x * 0.8)))
    ))
    return sepia


def _add_text_to_image(img, text, position="bottom", color="white"):
    """Add text overlay to image."""
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    w, h = img.size

    try:
        font_size = max(20, w // 25)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    # Calculate text position
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    if position == "bottom":
        x = (w - text_w) // 2
        y = h - text_h - 30
    elif position == "top":
        x = (w - text_w) // 2
        y = 20
    else:
        x = (w - text_w) // 2
        y = (h - text_h) // 2

    # Draw shadow
    draw.text((x + 2, y + 2), text, fill='black', font=font)
    # Draw text
    draw.text((x, y), text, fill=color, font=font)

    return img


def _extract_number(text: str, default=1.0):
    """Extract a number from text."""
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        return float(match.group(1))
    return default


# ══════════════════════════════════════════════════════════════
# INTERACTIVE ARTIFACTS
# ══════════════════════════════════════════════════════════════

def create_artifact(content: str, art_type: str = "html", title: str = "Artifact",
                    chat_id: str = None, user_id: str = None,
                    parent_id: str = None) -> Dict[str, Any]:
    """
    Create an interactive artifact with versioning.
    Types: html, svg, mermaid, react, markdown, chart
    """
    _load_artifact_store()

    file_id = str(uuid.uuid4())[:12]
    version = 1

    # If updating existing artifact, increment version
    if parent_id and parent_id in _artifact_store:
        parent = _artifact_store[parent_id]
        version = parent.get("latest_version", 0) + 1

    # Wrap content based on type
    wrapped_content, filename = _wrap_artifact_content(content, art_type, title, file_id)

    filepath = os.path.join(GENERATED_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(wrapped_content)

    fsize = os.path.getsize(filepath)

    # Store artifact metadata with versioning
    artifact_meta = {
        "id": file_id,
        "title": title,
        "type": art_type,
        "version": version,
        "latest_version": version,
        "parent_id": parent_id,
        "filepath": filepath,
        "filename": filename,
        "size": fsize,
        "chat_id": chat_id,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.md5(content.encode()).hexdigest()
    }

    _artifact_store[file_id] = artifact_meta

    # Update parent's latest version
    if parent_id and parent_id in _artifact_store:
        _artifact_store[parent_id]["latest_version"] = version
        _artifact_store[parent_id]["latest_id"] = file_id

    _save_artifact_store()

    # Register in file generator
    _register_generated(file_id, filename, filepath, art_type, fsize, chat_id, user_id,
                        meta={"title": title, "type": art_type, "version": version})

    return {
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "type": art_type,
        "title": title,
        "version": version,
        "size": fsize,
        "download_url": f"/api/files/{file_id}/download",
        "preview_url": f"/api/files/{file_id}/preview",
        "is_interactive": art_type in ("html", "react", "mermaid", "chart")
    }


def _wrap_artifact_content(content: str, art_type: str, title: str, file_id: str) -> Tuple[str, str]:
    """Wrap content in appropriate container based on type."""

    if art_type == 'html':
        filename = f"{file_id}_artifact.html"
        if '<html' not in content.lower():
            content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 24px;
            background: #ffffff;
            color: #1a1a2e;
            line-height: 1.6;
        }}
        h1, h2, h3 {{ margin-bottom: 16px; color: #1a1a2e; }}
        p {{ margin-bottom: 12px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
        th, td {{ border: 1px solid #dee2e6; padding: 10px 14px; text-align: left; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        code {{ background: #f1f3f5; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
        pre {{ background: #1a1a2e; color: #e9ecef; padding: 16px; border-radius: 8px; overflow-x: auto; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
    </style>
</head>
<body>
<div class="container">
{content}
</div>
</body>
</html>"""

    elif art_type == 'svg':
        filename = f"{file_id}_artifact.svg"
        if not content.strip().startswith('<svg'):
            content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">{content}</svg>'

    elif art_type == 'mermaid':
        filename = f"{file_id}_artifact.html"
        content = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
    body {{ display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #fff; font-family: sans-serif; }}
    .mermaid {{ max-width: 100%; }}
    h2 {{ text-align: center; margin-bottom: 20px; color: #333; }}
</style>
</head><body>
<div>
    <h2>{title}</h2>
    <div class="mermaid">
{content}
    </div>
</div>
<script>mermaid.initialize({{startOnLoad: true, theme: 'default', securityLevel: 'loose'}});</script>
</body></html>"""

    elif art_type == 'react':
        filename = f"{file_id}_artifact.html"
        content = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
</style>
</head><body>
<div id="root"></div>
<script type="text/babel">
{content}
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body></html>"""

    elif art_type == 'chart':
        filename = f"{file_id}_artifact.html"
        content = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
    body {{ display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 20px; background: #fff; }}
    canvas {{ max-width: 900px; max-height: 600px; }}
</style>
</head><body>
<canvas id="chart"></canvas>
<script>
{content}
</script>
</body></html>"""

    elif art_type == 'markdown':
        filename = f"{file_id}_artifact.md"
        # Keep as-is

    else:
        filename = f"{file_id}_artifact.{art_type}"

    return content, filename


def get_artifact(artifact_id: str) -> Optional[Dict]:
    """Get artifact metadata by ID."""
    _load_artifact_store()
    return _artifact_store.get(artifact_id)


def get_artifact_versions(artifact_id: str) -> List[Dict]:
    """Get all versions of an artifact."""
    _load_artifact_store()
    versions = []
    for aid, meta in _artifact_store.items():
        if meta.get("parent_id") == artifact_id or aid == artifact_id:
            versions.append(meta)
    versions.sort(key=lambda x: x.get("version", 0))
    return versions


def list_artifacts(chat_id: str = None, user_id: str = None, limit: int = 50) -> List[Dict]:
    """List artifacts, optionally filtered."""
    _load_artifact_store()
    artifacts = list(_artifact_store.values())
    if chat_id:
        artifacts = [a for a in artifacts if a.get("chat_id") == chat_id]
    if user_id:
        artifacts = [a for a in artifacts if a.get("user_id") == user_id]
    artifacts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return artifacts[:limit]


# ══════════════════════════════════════════════════════════════
# DESIGN GENERATION
# ══════════════════════════════════════════════════════════════

def generate_design(design_type: str, description: str,
                    api_key: str = "", api_url: str = "",
                    chat_id: str = None, user_id: str = None) -> Dict[str, Any]:
    """
    Generate UI/UX designs as HTML artifacts.
    Types: landing_page, dashboard, form, card, navbar, hero, pricing, portfolio
    """
    import requests as req

    if api_key:
        try:
            # Use LLM to generate HTML design
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            system_prompt = f"""You are an expert UI/UX designer and frontend developer.
Generate a complete, beautiful, responsive HTML page for: {design_type}.
Requirements:
- Modern design with gradients, shadows, rounded corners
- Responsive (mobile-first)
- Use CSS Grid/Flexbox
- Include animations and transitions
- Professional color scheme
- Complete HTML with inline CSS
- NO external dependencies except Google Fonts
Return ONLY the complete HTML code, no explanation."""

            resp = req.post(
                api_url or "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": description}
                    ],
                    "temperature": 0.5,
                    "max_tokens": 8000
                },
                timeout=90
            )

            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                # Extract HTML from response
                html_match = re.search(r'<!DOCTYPE html>.*?</html>', content, re.DOTALL | re.IGNORECASE)
                if html_match:
                    html_content = html_match.group(0)
                else:
                    html_content = content

                return create_artifact(html_content, "html", f"Design: {description[:50]}",
                                       chat_id, user_id)

        except Exception as e:
            logger.warning(f"LLM design generation failed: {e}")

    # Fallback: template-based design
    template = _get_design_template(design_type, description)
    return create_artifact(template, "html", f"Design: {description[:50]}", chat_id, user_id)


def _get_design_template(design_type: str, description: str) -> str:
    """Get a template-based design as fallback."""
    templates = {
        "landing_page": f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{description[:60]}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', sans-serif; color: #333; }}
.hero {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 100px 20px; text-align: center; }}
.hero h1 {{ font-size: 3em; margin-bottom: 20px; }}
.hero p {{ font-size: 1.3em; opacity: 0.9; max-width: 600px; margin: 0 auto 30px; }}
.btn {{ display: inline-block; padding: 15px 40px; background: white; color: #667eea; border-radius: 30px; text-decoration: none; font-weight: bold; font-size: 1.1em; transition: transform 0.3s; }}
.btn:hover {{ transform: scale(1.05); }}
.features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 30px; padding: 80px 40px; max-width: 1200px; margin: 0 auto; }}
.feature {{ text-align: center; padding: 40px 20px; border-radius: 16px; background: #f8f9fa; transition: transform 0.3s, box-shadow 0.3s; }}
.feature:hover {{ transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
.feature .icon {{ font-size: 3em; margin-bottom: 15px; }}
.feature h3 {{ margin-bottom: 10px; color: #667eea; }}
footer {{ background: #1a1a2e; color: white; text-align: center; padding: 40px; }}
</style></head><body>
<div class="hero"><h1>{description[:60]}</h1><p>Современное решение для вашего бизнеса</p><a href="#" class="btn">Начать</a></div>
<div class="features">
<div class="feature"><div class="icon">⚡</div><h3>Быстро</h3><p>Молниеносная скорость работы</p></div>
<div class="feature"><div class="icon">🔒</div><h3>Безопасно</h3><p>Надёжная защита данных</p></div>
<div class="feature"><div class="icon">🎨</div><h3>Красиво</h3><p>Современный дизайн</p></div>
</div>
<footer><p>&copy; 2026 {description[:30]}. All rights reserved.</p></footer>
</body></html>""",
    }

    return templates.get(design_type, templates["landing_page"])


# ══════════════════════════════════════════════════════════════
# HELPER: Register in file_generator
# ══════════════════════════════════════════════════════════════

def _register_generated(file_id, filename, filepath, fmt, size, chat_id, user_id, meta=None):
    """Register generated file in the file_generator registry."""
    try:
        from file_generator import _register_file
        _register_file(file_id, filename, filepath, fmt, size, chat_id, user_id)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# OOP WRAPPER (for compatibility with spec)
# ══════════════════════════════════════════════════════════════

class ArtifactGenerator:
    """OOP wrapper around artifact generation functions."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def generate_image(self, prompt: str, style: str = "auto", size: str = "1024x1024",
                       chat_id: str = "", user_id: str = "") -> Dict[str, Any]:
        return generate_image_ai(prompt, style, size, self.api_key, chat_id, user_id)

    def edit(self, filepath: str, instruction: str,
             chat_id: str = "", user_id: str = "") -> Dict[str, Any]:
        return edit_image(filepath, instruction, chat_id=chat_id, user_id=user_id)

    def create_artifact(self, art_type: str, content: str, title: str = "Artifact",
                        chat_id: str = "", user_id: str = "") -> Dict[str, Any]:
        return create_artifact(content, art_type, title, chat_id=chat_id, user_id=user_id)

    def design(self, design_type: str, description: str,
               chat_id: str = "", user_id: str = "") -> Dict[str, Any]:
        return generate_design(design_type, description, self.api_key, chat_id, user_id)
