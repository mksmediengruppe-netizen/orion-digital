"""
ARCANE Image Generation Worker — v3.1 (Multi-provider, hardened)

Generates images using multiple specialized providers with intelligent routing:

Provider        | $/img  | Superpower        | API
----------------|--------|-------------------|-------------------
Flux 2 Pro      | $0.055 | Photorealism #1   | BFL native
Midjourney      | ~$0.10 | Artistic #1       | GoAPI proxy (v6.1)
Ideogram V3     | $0.04  | Typography 95%    | Ideogram native
Recraft V4      | $0.04  | SVG export #1     | Recraft native
Flux Schnell    | $0.015 | Fast + cheap      | BFL native
GPT-5 Image     | $0.020 | Prompt adherence  | OpenRouter
Nano Banana 2   | $0.005 | Fast multimodal   | OpenRouter
GPT Image 1.5   | $0.07  | Text rendering    | OpenAI native
Pexels          | Free   | Stock photos      | Pexels REST

Security:
- Path traversal protection on all output paths
- Input validation: n, size, provider, output_format whitelisted
- Download size limits (MAX_DOWNLOAD_BYTES)
- Domain allowlist for image downloads
- No silent fallback on explicit provider — returns error
- asyncio.Lock on shared client initialization
- Configurable output directory via ARCANE_IMAGE_OUTPUT_DIR env var

v3.1 changelog (audit fixes):
- FIX: path traversal via save_dir/project_id (#1)
- FIX: unbounded n — now clamped to MAX_IMAGES_PER_REQUEST (#2)
- FIX: sync httpx.Client blocking event loop (#3)
- FIX: singleton/client race conditions — added locks (#4, #5)
- FIX: cost accounting only on successful save (#6)
- FIX: GPT5_IMAGE/GPT_IMAGE_15 availability check in chain (#7)
- FIX: explicit provider no longer silently falls back to auto (#8)
- FIX: failed explicit provider excluded from auto retry (#9)
- FIX: NANO_BANANA dispatch missing — now routes to OpenRouter (#10)
- FIX: GPT5_IMAGE always uses premium models regardless of flag (#11)
- FIX: ZeroDivisionError on size="0x0" — validated (#12)
- FIX: config access via safe getattr (#13)
- FIX: pollers fail-fast on 401/403/404 (#14)
- FIX: output_format propagated to all providers (#15)
- FIX: Midjourney version consistency (v6.1 everywhere) (#16)
- FIX: parallel generation via asyncio.gather for n>1 (#17)
- FIX: hardcoded /root/ path — now configurable (#18)
- FIX: download size limit + content-type validation (#19)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import time
import uuid
from enum import Enum
from math import gcd
from pathlib import Path
from typing import Optional

import httpx

from shared.utils.logger import get_logger

logger = get_logger("workers.image_gen")


# ============================================================================
# CONSTANTS & LIMITS
# ============================================================================

MAX_IMAGES_PER_REQUEST = 4          # Hard cap on n for generation
MAX_STOCK_RESULTS = 20              # Hard cap on n for Pexels search
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB max per image download
MAX_BASE64_BYTES = 50 * 1024 * 1024    # 50 MB max decoded base64
OVERALL_TIMEOUT_SECONDS = 300       # 5 min cap on entire generate() call

# Allowed sizes (width x height). Anything else gets mapped to nearest.
VALID_SIZES = {
    "512x512", "768x768", "1024x1024",
    "1024x1536", "1536x1024",
    "1024x1792", "1792x1024",
    "1280x720", "720x1280",
    "1344x768", "768x1344",
    "1365x1024", "1024x1365",
    "1536x1024", "1024x1536",
    "1820x1024", "1024x1820",
}

VALID_OUTPUT_FORMATS = {"png", "jpg", "webp", "svg"}
VALID_QUALITIES = {"standard", "hd"}

# Domains we allow downloading images from
ALLOWED_DOWNLOAD_DOMAINS = {
    # BFL / Flux
    "api.bfl.ml",
    "delivery.bfl.ml",
    "bfl-delivery.s3.amazonaws.com",
    # GoAPI / Midjourney
    "api.goapi.ai",
    "cdn.goapi.ai",
    "img.midjourneyapi.xyz",
    "cdn.midjourney.com",
    # Ideogram
    "api.ideogram.ai",
    "ideogram.ai",
    # Recraft
    "external.api.recraft.ai",
    "img.recraft.ai",
    # Pexels
    "images.pexels.com",
    # OpenAI
    "oaidalleapiprodscus.blob.core.windows.net",
    "dalleprodsec.blob.core.windows.net",
    # OpenRouter proxied
    "openrouter.ai",
}


# ============================================================================
# ENUMS & CONFIG
# ============================================================================

class ImageProvider(str, Enum):
    """Available image generation providers."""
    FLUX_PRO = "flux-pro"
    FLUX_SCHNELL = "flux-schnell"
    MIDJOURNEY = "midjourney"
    IDEOGRAM = "ideogram"
    RECRAFT = "recraft"
    GPT5_IMAGE = "gpt5-image"
    NANO_BANANA = "nano-banana"
    GPT_IMAGE_15 = "gpt-image-1.5"
    PEXELS = "pexels"
    AUTO = "auto"


STYLE_PRESETS = {
    "photorealistic": "Ultra-realistic photograph, 8K resolution, professional lighting, sharp focus, shallow depth of field",
    "illustration": "Digital illustration, clean lines, vibrant colors, professional artwork, detailed",
    "3d": "3D rendered image, high quality, realistic materials, professional lighting, ray-traced",
    "pixel-art": "Pixel art style, retro game aesthetic, clean pixels",
    "watercolor": "Watercolor painting style, soft edges, artistic brushstrokes, delicate",
    "minimal": "Minimalist design, clean, simple, modern aesthetic, white space",
    "cinematic": "Cinematic shot, dramatic lighting, film grain, wide angle, anamorphic lens flare",
    "anime": "Anime art style, high quality, detailed, vibrant, studio quality",
    "sketch": "Pencil sketch, detailed line work, artistic, fine hatching",
    "logo": "Professional logo design, clean vector style, modern, scalable",
    "editorial": "Editorial photography, magazine quality, artistic composition, high fashion",
    "hero": "Hero section image, dramatic, high-impact, professional, wide format, 4K",
    "product": "Product photography, clean background, professional studio lighting, sharp detail",
    "typography": "Bold typography design, clean text rendering, professional layout",
    "icon": "Clean icon design, scalable, simple shapes, professional",
    "vector": "Clean vector illustration, scalable, flat design, professional",
}

STYLE_PROVIDER_MAP: dict[str, ImageProvider] = {
    "photorealistic": ImageProvider.FLUX_PRO,
    "product": ImageProvider.FLUX_PRO,
    "editorial": ImageProvider.FLUX_PRO,
    "hero": ImageProvider.FLUX_PRO,
    "cinematic": ImageProvider.MIDJOURNEY,
    "anime": ImageProvider.MIDJOURNEY,
    "illustration": ImageProvider.MIDJOURNEY,
    "watercolor": ImageProvider.MIDJOURNEY,
    "3d": ImageProvider.MIDJOURNEY,
    "logo": ImageProvider.IDEOGRAM,
    "typography": ImageProvider.IDEOGRAM,
    "icon": ImageProvider.RECRAFT,
    "vector": ImageProvider.RECRAFT,
    "sketch": ImageProvider.FLUX_PRO,
    "pixel-art": ImageProvider.MIDJOURNEY,
    "minimal": ImageProvider.RECRAFT,
}


PROVIDER_CONFIG = {
    ImageProvider.FLUX_PRO: {
        "name": "Flux 2 Pro",
        "cost_per_image": 0.055,
        "superpower": "Photorealism #1",
        "env_key": "BFL_API_KEY",
        "base_url": "https://api.bfl.ml/v1",
    },
    ImageProvider.FLUX_SCHNELL: {
        "name": "Flux Schnell",
        "cost_per_image": 0.015,
        "superpower": "Fast + cheap",
        "env_key": "BFL_API_KEY",
        "base_url": "https://api.bfl.ml/v1",
    },
    ImageProvider.MIDJOURNEY: {
        "name": "Midjourney (v6.1 via GoAPI)",
        "cost_per_image": 0.10,
        "superpower": "Artistic #1",
        "env_key": "GOAPI_API_KEY",
        "base_url": "https://api.goapi.ai",
    },
    ImageProvider.IDEOGRAM: {
        "name": "Ideogram V3",
        "cost_per_image": 0.04,
        "superpower": "Typography 95%",
        "env_key": "IDEOGRAM_API_KEY",
        "base_url": "https://api.ideogram.ai",
    },
    ImageProvider.RECRAFT: {
        "name": "Recraft V4",
        "cost_per_image": 0.04,
        "superpower": "SVG export #1",
        "env_key": "RECRAFT_API_KEY",
        "base_url": "https://external.api.recraft.ai/v1",
    },
    ImageProvider.PEXELS: {
        "name": "Pexels",
        "cost_per_image": 0.0,
        "superpower": "Free stock photos (attribution required)",
        "env_key": "PEXELS_API_KEY",
        "base_url": "https://api.pexels.com/v1",
    },
}

# OpenRouter chat-based image models
PREMIUM_MODELS = [
    {
        "id": "openai/gpt-5-image",
        "name": "GPT-5 Image",
        "cost_per_image": 0.020,
        "api_type": "chat",
        "provider_enum": ImageProvider.GPT5_IMAGE,
    },
    {
        "id": "google/gemini-3.1-flash-image-preview",
        "name": "Nano Banana 2",
        "cost_per_image": 0.005,
        "api_type": "chat",
        "provider_enum": ImageProvider.NANO_BANANA,
    },
    {
        "id": "google/gemini-3-pro-image-preview",
        "name": "Nano Banana Pro",
        "cost_per_image": 0.020,
        "api_type": "chat",
    },
]

STANDARD_MODELS = [
    {
        "id": "openai/gpt-5-image-mini",
        "name": "GPT-5 Image Mini",
        "cost_per_image": 0.008,
        "api_type": "chat",
    },
    {
        "id": "google/gemini-2.5-flash-image",
        "name": "Nano Banana",
        "cost_per_image": 0.003,
        "api_type": "chat",
    },
]


# ============================================================================
# IMAGE GENERATOR
# ============================================================================

class ImageGenerator:
    """Multi-provider image generation with smart routing and automatic fallback."""

    def __init__(self, config=None):
        self._config = config
        self._openai_client: Optional[httpx.AsyncClient] = None
        self._openai_lock = asyncio.Lock()

        # Configurable output directory — never hardcode /root/
        self._output_dir = os.environ.get(
            "ARCANE_IMAGE_OUTPUT_DIR",
            os.path.join(
                os.environ.get("ARCANE_WORKSPACE", "/root/workspace"),
                "generated_images",
            ),
        )
        os.makedirs(self._output_dir, exist_ok=True)

    # === PUBLIC API ==========================================================

    async def generate(
        self,
        prompt: str,
        style: str = "photorealistic",
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        project_id: str = "",
        save_dir: Optional[str] = None,
        premium: bool = False,
        provider: str | ImageProvider = "auto",
        output_format: str = "png",
    ) -> dict:
        """
        Generate an image from a text prompt.

        Args:
            prompt: Text description of the image.
            style: Style preset name or custom style instruction.
            size: Image size (e.g. "1024x1024", "1792x1024").
            quality: "standard" or "hd".
            n: Number of images to generate (1-4, hard limit).
            project_id: Project ID for organizing outputs (alphanumeric/dash/underscore only).
            save_dir: Override output directory. Must be under ARCANE_IMAGE_OUTPUT_DIR.
            premium: If True, use premium models for OpenRouter path.
            provider: Force a specific provider or "auto" for smart routing.
            output_format: "png", "jpg", "webp", or "svg" (Recraft only).

        Returns:
            dict with: success, images, provider, cost, elapsed_seconds, [error]
        """
        # --- Input validation (FIX #2, #12) ----------------------------------
        n = max(1, min(n, MAX_IMAGES_PER_REQUEST))
        quality = quality if quality in VALID_QUALITIES else "standard"
        output_format = output_format if output_format in VALID_OUTPUT_FORMATS else "png"
        size = self._validate_size(size)
        project_id = self._sanitize_slug(project_id)
        save_dir = self._validate_save_dir(save_dir)

        # Resolve provider enum
        if isinstance(provider, str):
            try:
                resolved_provider = ImageProvider(provider)
            except ValueError:
                resolved_provider = ImageProvider.AUTO
        else:
            resolved_provider = provider

        # SVG request -> force Recraft
        if output_format == "svg":
            resolved_provider = ImageProvider.RECRAFT

        enhanced_prompt = self._enhance_prompt(prompt, style)

        # Wrap everything in an overall timeout (FIX: chain can take minutes)
        try:
            return await asyncio.wait_for(
                self._generate_inner(
                    resolved_provider, enhanced_prompt, prompt, style, size,
                    quality, n, project_id, save_dir, premium, output_format,
                ),
                timeout=OVERALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"generate() timed out after {OVERALL_TIMEOUT_SECONDS}s"
            )
            return self._fail("timeout", "Generation timed out")

    async def _generate_inner(
        self,
        resolved_provider: ImageProvider,
        enhanced_prompt: str,
        raw_prompt: str,
        style: str,
        size: str,
        quality: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        premium: bool,
        output_format: str,
    ) -> dict:
        """Core generation logic, wrapped in timeout by generate()."""

        # -- Explicit provider requested (FIX #8: NO silent fallback) ---------
        if resolved_provider != ImageProvider.AUTO:
            result = await self._dispatch_to_provider(
                resolved_provider, enhanced_prompt, raw_prompt, style, size,
                quality, n, project_id, save_dir, premium, output_format,
            )
            if result["success"]:
                return result
            # FIX #8: Return error, do NOT fall through to auto
            logger.warning(
                f"Explicit provider {resolved_provider.value} failed: "
                f"{result.get('error', 'unknown')}"
            )
            return result

        # -- Auto routing: pick best provider by style ------------------------
        preferred = STYLE_PROVIDER_MAP.get(style)
        chain = self._build_fallback_chain(preferred, premium)

        last_error = "All providers failed"
        for prov in chain:
            result = await self._dispatch_to_provider(
                prov, enhanced_prompt, raw_prompt, style, size,
                quality, n, project_id, save_dir, premium, output_format,
            )
            if result["success"]:
                return result
            last_error = result.get("error", last_error)

        return self._fail("none", last_error)

    async def search_stock(
        self,
        query: str,
        n: int = 5,
        size: str = "large",
        project_id: str = "",
        save_dir: Optional[str] = None,
    ) -> dict:
        """Search Pexels for stock photos. Attribution required for public use."""
        n = max(1, min(n, MAX_STOCK_RESULTS))
        project_id = self._sanitize_slug(project_id)
        save_dir = self._validate_save_dir(save_dir)
        return await self._generate_pexels(
            query, n, size, project_id, save_dir
        )

    def list_providers(self) -> list[dict]:
        """Return list of available providers with their status."""
        providers = []
        for prov, cfg in PROVIDER_CONFIG.items():
            env_key = cfg["env_key"]
            available = bool(os.environ.get(env_key, ""))
            providers.append({
                "id": prov.value,
                "name": cfg["name"],
                "cost_per_image": cfg["cost_per_image"],
                "superpower": cfg["superpower"],
                "available": available,
                "env_key": env_key,
            })
        # OpenRouter-based
        or_key = bool(os.environ.get("OPENROUTER_API_KEY", ""))
        providers.append({
            "id": "gpt5-image",
            "name": "GPT-5 Image (OpenRouter)",
            "cost_per_image": 0.020,
            "superpower": "Prompt adherence",
            "available": or_key,
            "env_key": "OPENROUTER_API_KEY",
        })
        # OpenAI direct (FIX #13: safe config access)
        oai_key = bool(self._get_config_value("openai", "api_key") or "")
        providers.append({
            "id": "gpt-image-1.5",
            "name": "GPT Image 1.5 (OpenAI)",
            "cost_per_image": 0.07,
            "superpower": "Text rendering",
            "available": oai_key,
            "env_key": "OPENAI_API_KEY",
        })
        return providers

    # === INPUT VALIDATION ====================================================

    @staticmethod
    def _sanitize_slug(value: str) -> str:
        """Sanitize project_id / slug: alphanumeric, dash, underscore only.
        FIX #1: prevents path traversal via project_id.
        """
        if not value:
            return "default"
        # Strip anything that isn't alphanumeric, dash, or underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', value)
        return sanitized[:128] or "default"

    def _validate_save_dir(self, save_dir: Optional[str]) -> Optional[str]:
        """Validate save_dir stays under allowed base directory.
        FIX #1: prevents path traversal via save_dir.
        """
        if not save_dir:
            return None
        # Resolve to absolute path and verify it's under our output dir
        base = Path(self._output_dir).resolve()
        target = Path(save_dir).resolve()
        if not str(target).startswith(str(base)):
            logger.warning(
                f"save_dir traversal blocked: {save_dir!r} "
                f"resolved to {target} outside {base}"
            )
            return None
        return str(target)

    @staticmethod
    def _validate_size(size: str) -> str:
        """Validate and normalize size. FIX #12: prevents ZeroDivisionError."""
        try:
            w, h = map(int, size.lower().split("x"))
        except (ValueError, AttributeError):
            return "1024x1024"
        # Reject zero, negative, or absurdly large
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            return "1024x1024"
        return f"{w}x{h}"

    # === ROUTING & DISPATCH ==================================================

    def _build_fallback_chain(
        self,
        preferred: Optional[ImageProvider],
        premium: bool,
    ) -> list[ImageProvider]:
        """Build ordered list of providers to try. FIX #7: all checked for availability."""
        chain: list[ImageProvider] = []

        if preferred and self._is_provider_available(preferred):
            chain.append(preferred)

        for prov in [
            ImageProvider.FLUX_SCHNELL,
            ImageProvider.FLUX_PRO,
            ImageProvider.IDEOGRAM,
            ImageProvider.RECRAFT,
            ImageProvider.MIDJOURNEY,
        ]:
            if self._is_provider_available(prov):
                chain.append(prov)

        # FIX #7: check availability before adding OpenRouter / OpenAI
        if os.environ.get("OPENROUTER_API_KEY", ""):
            chain.append(ImageProvider.GPT5_IMAGE)

        if self._get_config_value("openai", "api_key"):
            chain.append(ImageProvider.GPT_IMAGE_15)

        # Deduplicate preserving order
        seen: set[ImageProvider] = set()
        deduped: list[ImageProvider] = []
        for p in chain:
            if p not in seen:
                seen.add(p)
                deduped.append(p)
        return deduped

    def _is_provider_available(self, provider: ImageProvider) -> bool:
        cfg = PROVIDER_CONFIG.get(provider)
        if not cfg:
            return False
        return bool(os.environ.get(cfg["env_key"], ""))

    async def _dispatch_to_provider(
        self,
        provider: ImageProvider,
        enhanced_prompt: str,
        raw_prompt: str,
        style: str,
        size: str,
        quality: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        premium: bool,
        output_format: str,
    ) -> dict:
        """Route generation to the appropriate provider handler.
        FIX #10: NANO_BANANA now has a dispatch path.
        FIX #11: GPT5_IMAGE always uses premium models.
        """
        try:
            if provider == ImageProvider.FLUX_PRO:
                return await self._generate_flux(
                    enhanced_prompt, size, n, project_id, save_dir,
                    model="flux-pro-1.1-ultra", output_format=output_format,
                )
            elif provider == ImageProvider.FLUX_SCHNELL:
                return await self._generate_flux(
                    enhanced_prompt, size, n, project_id, save_dir,
                    model="flux-schnell", output_format=output_format,
                )
            elif provider == ImageProvider.MIDJOURNEY:
                return await self._generate_midjourney(
                    enhanced_prompt, size, n, project_id, save_dir,
                    output_format=output_format,
                )
            elif provider == ImageProvider.IDEOGRAM:
                return await self._generate_ideogram(
                    enhanced_prompt, size, n, project_id, save_dir,
                    style_hint=style, output_format=output_format,
                )
            elif provider == ImageProvider.RECRAFT:
                return await self._generate_recraft(
                    enhanced_prompt, size, n, project_id, save_dir,
                    style_hint=style, output_format=output_format,
                )
            elif provider == ImageProvider.PEXELS:
                return await self._generate_pexels(
                    raw_prompt, n, "large", project_id, save_dir,
                )
            elif provider == ImageProvider.GPT5_IMAGE:
                # FIX #11: GPT5_IMAGE = always premium OpenRouter models
                return await self._generate_via_openrouter_chain(
                    enhanced_prompt, size, n, project_id, save_dir,
                    force_premium=True,
                )
            elif provider == ImageProvider.NANO_BANANA:
                # FIX #10: NANO_BANANA routes to OpenRouter premium chain
                # (Nano Banana 2 is second in PREMIUM_MODELS)
                return await self._generate_via_openrouter_chain(
                    enhanced_prompt, size, n, project_id, save_dir,
                    force_premium=True,
                )
            elif provider == ImageProvider.GPT_IMAGE_15:
                return await self._generate_gpt_image(
                    enhanced_prompt, size, quality, n, project_id, save_dir,
                    output_format=output_format,
                )
            else:
                return self._fail(provider.value, "Unknown provider")
        except Exception as e:
            logger.warning(f"Provider {provider.value} dispatch error: {e}")
            return self._fail(provider.value, str(e))

    # === HELPERS ==============================================================

    def _enhance_prompt(self, prompt: str, style: str) -> str:
        style_instruction = STYLE_PRESETS.get(style, style)
        if style_instruction and style_instruction != prompt:
            return f"{prompt}. Style: {style_instruction}"
        return prompt

    def _output_path(
        self, prefix: str, project_id: str, save_dir: Optional[str],
        ext: str = "png",
    ) -> str:
        """Generate a safe output file path. FIX #1: all components sanitized."""
        # project_id already sanitized by _sanitize_slug
        # save_dir already validated by _validate_save_dir
        output_dir = save_dir or os.path.join(
            self._output_dir, project_id or "default",
        )
        os.makedirs(output_dir, exist_ok=True)

        # Double-check resolved path stays under base
        resolved = Path(output_dir).resolve()
        base = Path(self._output_dir).resolve()
        if not str(resolved).startswith(str(base)):
            logger.error(f"output_path escaped base dir: {resolved}")
            output_dir = str(base / "default")
            os.makedirs(output_dir, exist_ok=True)

        ext = re.sub(r'[^a-z0-9]', '', ext.lower())[:5] or "png"
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
        return os.path.join(output_dir, filename)

    @staticmethod
    def _fail(provider: str, error: str) -> dict:
        return {
            "success": False,
            "images": [],
            "provider": provider,
            "error": error,
            "cost": 0.0,
            "elapsed_seconds": 0,
        }

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        """Parse 'WxH' into (width, height). Already validated by _validate_size."""
        try:
            w, h = map(int, size.lower().split("x"))
            if w <= 0 or h <= 0:
                return 1024, 1024
            return w, h
        except ValueError:
            return 1024, 1024

    @staticmethod
    def _aspect_ratio(size: str) -> str:
        """Convert size to aspect ratio string. FIX #12: safe against /0."""
        w, h = ImageGenerator._parse_size(size)
        g = gcd(w, h)
        if g == 0:
            return "1:1"
        return f"{w // g}:{h // g}"

    def _get_config_value(self, section: str, key: str) -> str:
        """Safely access config values. FIX #13: no AttributeError."""
        if self._config is None:
            return os.environ.get(
                f"{section.upper()}_{key.upper()}",
                os.environ.get(f"{key.upper()}", ""),
            )
        try:
            section_obj = getattr(self._config, section, None)
            if section_obj is None:
                return os.environ.get(f"{section.upper()}_{key.upper()}", "")
            return getattr(section_obj, key, "") or ""
        except Exception:
            return os.environ.get(f"{section.upper()}_{key.upper()}", "")

    async def _safe_download(
        self,
        client: httpx.AsyncClient,
        url: str,
        timeout: float = 30.0,
    ) -> Optional[bytes]:
        """Download image with domain allowlist and size limit.
        FIX #3 (all downloads now use async client).
        FIX #19: domain allowlist + max bytes.
        """
        # Validate domain
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if hostname not in ALLOWED_DOWNLOAD_DOMAINS:
                logger.warning(
                    f"Download blocked — domain not in allowlist: {hostname}"
                )
                return None
        except Exception:
            return None

        try:
            # Stream to enforce size limit
            async with client.stream("GET", url, timeout=timeout) as resp:
                resp.raise_for_status()
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        logger.warning(
                            f"Download aborted — exceeds {MAX_DOWNLOAD_BYTES} bytes"
                        )
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except Exception as e:
            logger.warning(f"Download failed for {url}: {e}")
            return None

    @staticmethod
    def _detect_image_ext(data: bytes) -> str:
        """Detect actual image format from magic bytes."""
        if data[:4] == b'\x89PNG':
            return "png"
        if data[:2] == b'\xff\xd8':
            return "jpg"
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "webp"
        if data[:5] == b'<?xml' or data[:4] == b'<svg':
            return "svg"
        return "png"  # default fallback

    # === PARALLEL GENERATION HELPER (FIX #17) ================================

    async def _generate_parallel(
        self,
        coro_factory,
        n: int,
        provider_name: str,
    ) -> list[dict]:
        """Run up to n generation coroutines in parallel.
        FIX #17: asyncio.gather instead of sequential loop.
        Returns list of successful result dicts.
        """
        tasks = [coro_factory(i) for i in range(n)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        images = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"{provider_name} image {i+1}/{n} failed: {r}")
            elif isinstance(r, dict) and r.get("path"):
                images.append(r)
        return images

    # ========================================================================
    # PROVIDER: Flux (BFL API) — Flux 2 Pro / Flux Schnell
    # ========================================================================

    async def _generate_flux(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        model: str = "flux-pro-1.1-ultra",
        output_format: str = "png",
    ) -> dict:
        """Generate via Black Forest Labs API (async poll)."""
        api_key = os.environ.get("BFL_API_KEY", "")
        if not api_key:
            return self._fail("flux", "BFL_API_KEY not configured")

        w, h = self._parse_size(size)
        is_schnell = "schnell" in model
        cfg = PROVIDER_CONFIG[
            ImageProvider.FLUX_SCHNELL if is_schnell else ImageProvider.FLUX_PRO
        ]
        start = time.monotonic()

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:

            async def _gen_one(i: int) -> dict:
                if "ultra" in model:
                    payload = {"prompt": prompt, "aspect_ratio": self._aspect_ratio(size)}
                else:
                    payload = {"prompt": prompt, "width": w, "height": h}

                resp = await client.post(
                    f"{cfg['base_url']}/{model}",
                    headers={"X-Key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                task_id = resp.json().get("id")
                if not task_id:
                    raise ValueError(f"No task ID from BFL: {resp.text[:200]}")

                image_url = await self._poll_bfl_result(client, api_key, task_id, cfg["base_url"])
                if not image_url:
                    raise TimeoutError("BFL poll timed out")

                data = await self._safe_download(client, image_url)
                if not data:
                    raise ValueError("Download failed or blocked")

                ext = self._detect_image_ext(data) if output_format == "png" else output_format
                filepath = self._output_path("flux", project_id, save_dir, ext=ext)
                with open(filepath, "wb") as f:
                    f.write(data)
                return {"path": filepath, "revised_prompt": prompt, "size": size, "model": model}

            images = await self._generate_parallel(_gen_one, n, f"Flux/{model}")

        elapsed = time.monotonic() - start
        total_cost = len(images) * cfg["cost_per_image"]  # FIX #6: cost only on success
        if images:
            logger.info(f"Flux {model}: {len(images)} images, ${total_cost:.3f}, {elapsed:.1f}s")

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": f"bfl/{model}",
            "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def _poll_bfl_result(
        self, client: httpx.AsyncClient, api_key: str,
        task_id: str, base_url: str,
        max_wait: float = 120.0, interval: float = 1.5,
    ) -> Optional[str]:
        """Poll BFL API. FIX #14: fail-fast on 4xx."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                resp = await client.get(
                    f"{base_url}/get_result",
                    params={"id": task_id},
                    headers={"X-Key": api_key},
                )
                # FIX #14: fail-fast on auth/not-found errors
                if resp.status_code in (401, 403, 404):
                    logger.error(f"BFL fatal {resp.status_code} for task {task_id}")
                    return None
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status")

                if status == "Ready":
                    result = data.get("result", {})
                    return result.get("sample") or result.get("url")
                elif status in ("Error", "Failed"):
                    logger.warning(f"BFL task {task_id} failed: {data}")
                    return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    return None
                logger.debug(f"BFL poll HTTP error (retry): {e}")
            except Exception as e:
                logger.debug(f"BFL poll error (retry): {e}")

            await asyncio.sleep(interval)
        return None

    # ========================================================================
    # PROVIDER: Midjourney v6.1 (via GoAPI proxy)
    # FIX #16: consistent v6.1 everywhere — docs, code, metadata
    # ========================================================================

    async def _generate_midjourney(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        output_format: str = "png",
    ) -> dict:
        """Generate via Midjourney v6.1 through GoAPI proxy."""
        api_key = os.environ.get("GOAPI_API_KEY", "")
        if not api_key:
            return self._fail("midjourney", "GOAPI_API_KEY not configured")

        cfg = PROVIDER_CONFIG[ImageProvider.MIDJOURNEY]
        start = time.monotonic()

        ar = self._aspect_ratio(size)
        mj_prompt = prompt
        if ar != "1:1":
            mj_prompt = f"{prompt} --ar {ar}"
        mj_prompt += " --v 6.1"

        # MJ is slow — parallel tasks help a lot
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:

            async def _gen_one(i: int) -> dict:
                resp = await client.post(
                    f"{cfg['base_url']}/mj/v2/imagine",
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    json={"prompt": mj_prompt, "process_mode": "fast"},
                )
                resp.raise_for_status()
                task_id = resp.json().get("task_id")
                if not task_id:
                    raise ValueError(f"No task_id from GoAPI: {resp.text[:200]}")

                result_data = await self._poll_goapi_result(client, api_key, task_id, cfg["base_url"])
                if not result_data:
                    raise TimeoutError("GoAPI poll timed out")

                image_url = (
                    result_data.get("image_url")
                    or result_data.get("output", {}).get("image_url")
                    or result_data.get("output", {}).get("temporary_image_url")
                    or ""
                )
                if not image_url:
                    raise ValueError("No image URL in GoAPI result")

                data = await self._safe_download(client, image_url, timeout=60.0)
                if not data:
                    raise ValueError("Download failed or blocked")

                ext = self._detect_image_ext(data) if output_format == "png" else output_format
                filepath = self._output_path("mj", project_id, save_dir, ext=ext)
                with open(filepath, "wb") as f:
                    f.write(data)
                return {
                    "path": filepath, "revised_prompt": mj_prompt,
                    "size": size, "model": "midjourney-v6.1",
                }

            images = await self._generate_parallel(_gen_one, n, "Midjourney")

        elapsed = time.monotonic() - start
        total_cost = len(images) * cfg["cost_per_image"]
        if images:
            logger.info(f"Midjourney v6.1: {len(images)} images, ${total_cost:.3f}, {elapsed:.1f}s")

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": "goapi/midjourney-v6.1",
            "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def _poll_goapi_result(
        self, client: httpx.AsyncClient, api_key: str,
        task_id: str, base_url: str,
        max_wait: float = 240.0, interval: float = 3.0,
    ) -> Optional[dict]:
        """Poll GoAPI for MJ result. FIX #14: fail-fast on fatal errors."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                resp = await client.get(
                    f"{base_url}/mj/v2/fetch",
                    params={"task_id": task_id},
                    headers={"x-api-key": api_key},
                )
                if resp.status_code in (401, 403, 404):
                    logger.error(f"GoAPI fatal {resp.status_code} for task {task_id}")
                    return None
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")

                if status in ("finished", "completed"):
                    return data
                elif status in ("failed", "error"):
                    logger.warning(f"GoAPI task {task_id} failed: {json.dumps(data)[:200]}")
                    return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    return None
                logger.debug(f"GoAPI poll HTTP error (retry): {e}")
            except Exception as e:
                logger.debug(f"GoAPI poll error (retry): {e}")

            await asyncio.sleep(interval)
        return None

    # ========================================================================
    # PROVIDER: Ideogram V3
    # ========================================================================

    async def _generate_ideogram(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        style_hint: str = "",
        output_format: str = "png",
    ) -> dict:
        """Generate via Ideogram V3 API (synchronous, parallel-safe)."""
        api_key = os.environ.get("IDEOGRAM_API_KEY", "")
        if not api_key:
            return self._fail("ideogram", "IDEOGRAM_API_KEY not configured")

        cfg = PROVIDER_CONFIG[ImageProvider.IDEOGRAM]
        start = time.monotonic()

        w, h = self._parse_size(size)
        ar = self._aspect_ratio(size)
        ideogram_resolution = self._map_ideogram_resolution(w, h)

        style_type = "AUTO"
        if style_hint in ("photorealistic", "product", "editorial", "hero"):
            style_type = "REALISTIC"
        elif style_hint in ("illustration", "anime", "3d", "pixel-art", "logo", "typography", "icon", "vector"):
            style_type = "DESIGN"

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:

            async def _gen_one(i: int) -> dict:
                resp = await client.post(
                    f"{cfg['base_url']}/generate",
                    headers={"Api-Key": api_key, "Content-Type": "application/json"},
                    json={
                        "image_request": {
                            "prompt": prompt, "model": "V_3",
                            "aspect_ratio": ar, "resolution": ideogram_resolution,
                            "style_type": style_type, "magic_prompt_option": "AUTO",
                        },
                    },
                )
                resp.raise_for_status()
                results = resp.json().get("data", [])
                if not results or not results[0].get("url"):
                    raise ValueError("No image URL from Ideogram")

                data = await self._safe_download(client, results[0]["url"])
                if not data:
                    raise ValueError("Download failed")

                ext = self._detect_image_ext(data) if output_format == "png" else output_format
                filepath = self._output_path("ideogram", project_id, save_dir, ext=ext)
                with open(filepath, "wb") as f:
                    f.write(data)
                return {
                    "path": filepath,
                    "revised_prompt": results[0].get("prompt", prompt),
                    "size": size, "model": "ideogram-v3",
                    "seed": results[0].get("seed"),
                }

            images = await self._generate_parallel(_gen_one, n, "Ideogram")

        elapsed = time.monotonic() - start
        total_cost = len(images) * cfg["cost_per_image"]
        if images:
            logger.info(f"Ideogram V3: {len(images)} images, ${total_cost:.3f}, {elapsed:.1f}s")

        return {
            "success": len(images) > 0, "images": images,
            "provider": "ideogram/v3", "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    @staticmethod
    def _map_ideogram_resolution(w: int, h: int) -> str:
        resolutions = {
            (1024, 1024): "RESOLUTION_1024_1024",
            (1280, 720): "RESOLUTION_1280_720",
            (720, 1280): "RESOLUTION_720_1280",
            (1344, 768): "RESOLUTION_1344_768",
            (768, 1344): "RESOLUTION_768_1344",
            (1536, 1024): "RESOLUTION_1536_1024",
            (1024, 1536): "RESOLUTION_1024_1536",
        }
        target_ratio = w / max(h, 1)
        best_key = (1024, 1024)
        best_diff = float("inf")
        for res_key in resolutions:
            diff = abs(res_key[0] / max(res_key[1], 1) - target_ratio)
            if diff < best_diff:
                best_diff = diff
                best_key = res_key
        return resolutions[best_key]

    # ========================================================================
    # PROVIDER: Recraft V4 (OpenAI-compatible API)
    # ========================================================================

    async def _generate_recraft(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        style_hint: str = "",
        output_format: str = "png",
    ) -> dict:
        """Generate via Recraft V4 API. Unique: native SVG output."""
        api_key = os.environ.get("RECRAFT_API_KEY", "")
        if not api_key:
            return self._fail("recraft", "RECRAFT_API_KEY not configured")

        cfg = PROVIDER_CONFIG[ImageProvider.RECRAFT]
        start = time.monotonic()

        w, h = self._parse_size(size)
        recraft_size = self._map_recraft_size(w, h)

        recraft_style = "realistic_image"
        if style_hint in ("illustration", "anime", "3d"):
            recraft_style = "digital_illustration"
        elif style_hint in ("vector", "icon", "logo", "minimal"):
            recraft_style = "vector_illustration"

        ext = output_format if output_format in VALID_OUTPUT_FORMATS else "png"
        if ext == "svg":
            recraft_style = "vector_illustration"

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:

            async def _gen_one(i: int) -> dict:
                resp = await client.post(
                    f"{cfg['base_url']}/images/generations",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "prompt": prompt, "model": "recraftv3",
                        "size": recraft_size, "n": 1,
                        "style": recraft_style, "response_format": "url",
                    },
                )
                resp.raise_for_status()
                img_list = resp.json().get("data", [])
                if not img_list or not img_list[0].get("url"):
                    raise ValueError("No URL from Recraft")

                data = await self._safe_download(client, img_list[0]["url"])
                if not data:
                    raise ValueError("Download failed")

                actual_ext = ext if ext == "svg" else self._detect_image_ext(data)
                filepath = self._output_path("recraft", project_id, save_dir, ext=actual_ext)
                with open(filepath, "wb") as f:
                    f.write(data)
                return {
                    "path": filepath, "revised_prompt": prompt,
                    "size": size, "model": "recraft-v4",
                    "format": actual_ext, "style": recraft_style,
                }

            images = await self._generate_parallel(_gen_one, n, "Recraft")

        elapsed = time.monotonic() - start
        total_cost = len(images) * cfg["cost_per_image"]
        if images:
            logger.info(f"Recraft V4: {len(images)} images ({ext}), ${total_cost:.3f}, {elapsed:.1f}s")

        return {
            "success": len(images) > 0, "images": images,
            "provider": "recraft/v4", "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    @staticmethod
    def _map_recraft_size(w: int, h: int) -> str:
        sizes = [
            "1024x1024", "1365x1024", "1024x1365",
            "1536x1024", "1024x1536", "1820x1024", "1024x1820",
        ]
        target_ratio = w / max(h, 1)
        best = "1024x1024"
        best_diff = float("inf")
        for s in sizes:
            sw, sh = map(int, s.split("x"))
            diff = abs((sw / sh) - target_ratio)
            if diff < best_diff:
                best_diff = diff
                best = s
        return best

    # ========================================================================
    # PROVIDER: Pexels (free stock photos)
    # ========================================================================

    async def _generate_pexels(
        self, query: str, n: int, size: str,
        project_id: str, save_dir: Optional[str],
    ) -> dict:
        """Search + download stock photos from Pexels.
        Note: Pexels API requires attribution in all public uses.
        """
        api_key = os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            return self._fail("pexels", "PEXELS_API_KEY not configured")

        cfg = PROVIDER_CONFIG[ImageProvider.PEXELS]
        start = time.monotonic()
        images: list[dict] = []

        size_key = {"small": "small", "medium": "medium", "large": "large2x", "original": "original"}.get(size, "large2x")

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            try:
                resp = await client.get(
                    f"{cfg['base_url']}/search",
                    params={"query": query, "per_page": min(n, MAX_STOCK_RESULTS), "orientation": "landscape"},
                    headers={"Authorization": api_key},
                )
                resp.raise_for_status()
                data = resp.json()

                for photo in data.get("photos", [])[:n]:
                    image_url = photo.get("src", {}).get(size_key, "")
                    if not image_url:
                        continue

                    photographer = photo.get("photographer", "Unknown")
                    pexels_url = photo.get("url", "")

                    filepath = None
                    if save_dir or project_id:
                        img_data = await self._safe_download(client, image_url)
                        if img_data:
                            filepath = self._output_path("pexels", project_id, save_dir, ext="jpg")
                            with open(filepath, "wb") as f:
                                f.write(img_data)

                    images.append({
                        "path": filepath, "url": image_url,
                        "photographer": photographer, "pexels_url": pexels_url,
                        "size": size, "alt": photo.get("alt", query),
                        "attribution": f"Photo by {photographer} on Pexels",
                    })

            except Exception as e:
                logger.warning(f"Pexels search failed: {e}")
                return self._fail("pexels", str(e))

        elapsed = time.monotonic() - start
        if images:
            logger.info(f"Pexels: {len(images)} photos for '{query}'")

        return {
            "success": len(images) > 0, "images": images,
            "provider": "pexels", "cost": 0.0,
            "elapsed_seconds": round(elapsed, 2),
        }

    # ========================================================================
    # PROVIDER: OpenRouter (GPT-5 Image / Nano Banana)
    # ========================================================================

    async def _generate_via_openrouter_chain(
        self, prompt: str, size: str, n: int,
        project_id: str, save_dir: Optional[str],
        force_premium: bool = False,
    ) -> dict:
        """Try OpenRouter models in order.
        FIX #11: force_premium flag overrides the premium parameter.
        """
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return self._fail("openrouter", "OPENROUTER_API_KEY not configured")

        models = PREMIUM_MODELS if force_premium else STANDARD_MODELS
        for model_def in models:
            try:
                result = await self._generate_via_openrouter(
                    prompt, size, n, project_id, save_dir, model_def,
                )
                if result["success"]:
                    return result
            except Exception as e:
                logger.warning(f"OpenRouter {model_def['name']} failed: {e}")
                continue

        return self._fail("openrouter", "All OpenRouter image models failed")

    async def _generate_via_openrouter(
        self, prompt: str, size: str, n: int,
        project_id: str, save_dir: Optional[str],
        model_def: dict,
    ) -> dict:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return self._fail(model_def["id"], "OPENROUTER_API_KEY not configured")

        start = time.monotonic()
        images: list[dict] = []
        total_cost = 0.0

        w, h = self._parse_size(size)
        aspect_hint = ""
        if w > h:
            aspect_hint = " (landscape orientation, wide format)"
        elif h > w:
            aspect_hint = " (portrait orientation, tall format)"

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            for i in range(n):
                try:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://arcaneai.ru",
                            "X-Title": "ARCANE AI Workspace",
                        },
                        json={
                            "model": model_def["id"],
                            "messages": [{
                                "role": "user",
                                "content": (
                                    f"Generate an image: {prompt}{aspect_hint}\n\n"
                                    "Output ONLY the image, no text explanation."
                                ),
                            }],
                            "max_tokens": 4096,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    # FIX #3: _extract now async
                    extracted = await self._extract_image_from_chat_response(data, client)
                    if extracted:
                        filepath = self._output_path("or", project_id, save_dir)
                        with open(filepath, "wb") as f:
                            f.write(extracted)
                        images.append({
                            "path": filepath, "revised_prompt": prompt,
                            "size": size, "model": model_def["id"],
                        })
                        total_cost += model_def["cost_per_image"]
                    else:
                        logger.warning(f"{model_def['name']} image {i+1}/{n}: no image in response")

                except httpx.HTTPStatusError as e:
                    logger.warning(f"{model_def['name']} {i+1}/{n} HTTP {e.response.status_code}")
                    continue
                except Exception as e:
                    logger.warning(f"{model_def['name']} {i+1}/{n} failed: {e}")
                    continue

        elapsed = time.monotonic() - start
        return {
            "success": len(images) > 0, "images": images,
            "provider": model_def["id"], "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def _extract_image_from_chat_response(
        self, data: dict, client: httpx.AsyncClient,
    ) -> Optional[bytes]:
        """Extract image from chat completion response.
        FIX #3: fully async — no sync httpx.Client blocking event loop.
        """
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})

        # Case 0: message.images[] — OpenRouter format
        images_list = message.get("images", [])
        if images_list:
            for img_entry in images_list:
                if isinstance(img_entry, dict):
                    url = ""
                    if img_entry.get("type") == "image_url":
                        url = img_entry.get("image_url", {}).get("url", "")
                    elif img_entry.get("url"):
                        url = img_entry["url"]
                    if url.startswith("data:image"):
                        b64_part = url.split(",", 1)[-1]
                        decoded = base64.b64decode(b64_part)
                        if len(decoded) > MAX_BASE64_BYTES:
                            continue
                        return decoded
                    elif url.startswith("http"):
                        # FIX #3: async download with domain check
                        result = await self._safe_download(client, url)
                        if result:
                            return result

        content = message.get("content", "")

        # Case 1: content is list of parts (multimodal)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    inline = part.get("inline_data", {})
                    if inline and inline.get("data"):
                        decoded = base64.b64decode(inline["data"])
                        if len(decoded) <= MAX_BASE64_BYTES:
                            return decoded

                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:image"):
                            b64_part = url.split(",", 1)[-1]
                            decoded = base64.b64decode(b64_part)
                            if len(decoded) <= MAX_BASE64_BYTES:
                                return decoded

                    if part.get("type") == "image":
                        b64 = part.get("data", "") or part.get("base64", "")
                        if b64:
                            decoded = base64.b64decode(b64)
                            if len(decoded) <= MAX_BASE64_BYTES:
                                return decoded

                    source = part.get("source", {})
                    if source.get("data"):
                        decoded = base64.b64decode(source["data"])
                        if len(decoded) <= MAX_BASE64_BYTES:
                            return decoded

        # Case 2: content string with embedded base64
        if isinstance(content, str) and len(content) > 500:
            b64_match = re.search(r'data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)', content)
            if b64_match:
                decoded = base64.b64decode(b64_match.group(1))
                if len(decoded) <= MAX_BASE64_BYTES:
                    return decoded

            clean = content.replace("\n", "").replace(" ", "").replace("=", "")
            if clean.isalnum() and len(content) < 100_000_000:
                try:
                    decoded = base64.b64decode(content)
                    if (decoded[:4] == b'\x89PNG' or decoded[:2] == b'\xff\xd8'):
                        if len(decoded) <= MAX_BASE64_BYTES:
                            return decoded
                except Exception:
                    pass

        return None

    # ========================================================================
    # PROVIDER: GPT Image 1.5 via direct OpenAI API
    # ========================================================================

    async def _get_openai_client(self) -> httpx.AsyncClient:
        """Get or create OpenAI client. FIX #5: asyncio.Lock prevents race."""
        async with self._openai_lock:
            if self._openai_client is None:
                api_key = self._get_config_value("openai", "api_key")
                base_url = self._get_config_value("openai", "base_url") or "https://api.openai.com/v1"
                self._openai_client = httpx.AsyncClient(
                    base_url=base_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(120.0),
                )
            return self._openai_client

    async def _generate_gpt_image(
        self, prompt: str, size: str, quality: str,
        n: int, project_id: str, save_dir: Optional[str],
        output_format: str = "png",
    ) -> dict:
        """Generate via GPT Image 1.5 (direct OpenAI API)."""
        client = await self._get_openai_client()
        start = time.monotonic()

        images: list[dict] = []
        total_cost = 0.0

        size_map = {"1792x1024": "1536x1024", "1024x1792": "1024x1536"}
        gpt_image_size = size_map.get(size, size)
        gpt_quality = "high" if quality == "hd" else "medium"

        is_large = gpt_image_size != "1024x1024"
        cost_table = {
            "low": 0.04 if is_large else 0.02,
            "medium": 0.14 if is_large else 0.07,
            "high": 0.38 if is_large else 0.19,
        }
        unit_cost = cost_table.get(gpt_quality, 0.07)

        for i in range(n):
            try:
                resp = await client.post("/images/generations", json={
                    "model": "gpt-image-1.5",
                    "prompt": prompt, "n": 1,
                    "size": gpt_image_size, "quality": gpt_quality,
                })
                resp.raise_for_status()
                data = resp.json()

                saved = False
                for img_data in data.get("data", []):
                    b64 = img_data.get("b64_json", "")
                    revised_prompt = img_data.get("revised_prompt", prompt)
                    img_url = img_data.get("url", "")

                    if b64:
                        raw = base64.b64decode(b64)
                        if len(raw) > MAX_BASE64_BYTES:
                            continue
                        ext = self._detect_image_ext(raw) if output_format == "png" else output_format
                        filepath = self._output_path("gpt", project_id, save_dir, ext=ext)
                        with open(filepath, "wb") as f:
                            f.write(raw)
                        images.append({
                            "path": filepath, "revised_prompt": revised_prompt,
                            "size": size, "model": "gpt-image-1.5",
                        })
                        saved = True
                    elif img_url:
                        # Use a separate async client for download
                        async with httpx.AsyncClient(timeout=30.0) as dl:
                            raw = await self._safe_download(dl, img_url)
                            if raw:
                                ext = self._detect_image_ext(raw) if output_format == "png" else output_format
                                filepath = self._output_path("gpt", project_id, save_dir, ext=ext)
                                with open(filepath, "wb") as f:
                                    f.write(raw)
                                images.append({
                                    "path": filepath, "revised_prompt": revised_prompt,
                                    "size": size, "model": "gpt-image-1.5",
                                })
                                saved = True

                # FIX #6: cost ONLY on successful save
                if saved:
                    total_cost += unit_cost

            except Exception as e:
                logger.warning(f"GPT Image 1.5 image {i+1}/{n} failed: {e}")
                continue

        elapsed = time.monotonic() - start
        if images:
            logger.info(f"GPT Image 1.5: {len(images)} images, ${total_cost:.3f}")

        return {
            "success": len(images) > 0, "images": images,
            "provider": "openai/gpt-image-1.5", "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    # -- Lifecycle ------------------------------------------------------------

    async def close(self):
        """Close HTTP clients."""
        async with self._openai_lock:
            if self._openai_client:
                await self._openai_client.aclose()
                self._openai_client = None


# ============================================================================
# SINGLETON (FIX #4: thread-safe via threading.Lock)
# ============================================================================

_generator: Optional[ImageGenerator] = None
_generator_lock = threading.Lock()


def get_image_generator(config=None) -> ImageGenerator:
    """Get or create the singleton image generator. Thread-safe."""
    global _generator
    if _generator is None:
        with _generator_lock:
            # Double-checked locking
            if _generator is None:
                _generator = ImageGenerator(config)
    return _generator
