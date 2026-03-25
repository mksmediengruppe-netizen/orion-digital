"""
ORION TTS Tool
==============
Text-to-Speech using OpenAI-compatible API (via OpenRouter or direct OpenAI).
Generates audio files from text input.

Usage in agent_loop:
    from tts_tool import tool_text_to_speech
    result = tool_text_to_speech(text="Hello world", voice="alloy")
"""

import os
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Configuration ──
TTS_OUTPUT_DIR = os.environ.get("TTS_OUTPUT_DIR", "/tmp/orion_tts")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# TTS works best via direct OpenAI API; fallback to OpenRouter
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Available voices: alloy, echo, fable, onyx, nova, shimmer
DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"  # or "tts-1-hd" for higher quality


def tool_text_to_speech(
    text: str,
    voice: str = None,
    model: str = None,
    output_format: str = "mp3",
    speed: float = 1.0,
    **kwargs
) -> dict:
    """
    Convert text to speech audio file.
    
    Args:
        text: Text to convert (max 4096 chars)
        voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)
        model: TTS model (tts-1 or tts-1-hd)
        output_format: Audio format (mp3, opus, aac, flac, wav, pcm)
        speed: Speech speed (0.25 to 4.0)
    
    Returns:
        dict with success, file_path, duration_estimate, format
    """
    try:
        if not text or not text.strip():
            return {"success": False, "error": "Text is required"}
        
        # Truncate to API limit
        if len(text) > 4096:
            text = text[:4096]
            logger.warning("[TTS] Text truncated to 4096 characters")
        
        voice = voice or DEFAULT_VOICE
        model = model or DEFAULT_MODEL
        
        # Validate voice
        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        if voice not in valid_voices:
            voice = DEFAULT_VOICE
        
        # Validate speed
        speed = max(0.25, min(4.0, float(speed)))
        
        # Validate format
        valid_formats = ["mp3", "opus", "aac", "flac", "wav", "pcm"]
        if output_format not in valid_formats:
            output_format = "mp3"
        
        # Ensure output directory exists
        os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
        
        # Generate unique filename
        filename = f"tts_{uuid.uuid4().hex[:8]}_{int(time.time())}.{output_format}"
        output_path = os.path.join(TTS_OUTPUT_DIR, filename)
        
        # Try OpenAI API first (direct), then OpenRouter
        api_key = OPENAI_API_KEY or OPENROUTER_API_KEY
        base_url = None
        
        if OPENAI_API_KEY:
            base_url = "https://api.openai.com/v1"
        elif OPENROUTER_API_KEY:
            base_url = "https://openrouter.ai/api/v1"
        else:
            return {"success": False, "error": "No API key configured for TTS (need OPENAI_API_KEY or OPENROUTER_API_KEY)"}
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
            
            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format=output_format,
                speed=speed,
            )
            
            # Stream to file
            response.stream_to_file(output_path)
            
        except ImportError:
            # Fallback: use requests directly
            import requests
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": output_format,
                "speed": speed,
            }
            
            resp = requests.post(
                f"{base_url}/audio/speech",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            
            with open(output_path, "wb") as f:
                f.write(resp.content)
        
        # Estimate duration (~150 words per minute at speed 1.0)
        word_count = len(text.split())
        duration_estimate = (word_count / 150) * 60 / speed
        
        file_size = os.path.getsize(output_path)
        
        logger.info(f"[TTS] Generated {output_format} ({file_size} bytes): {output_path}")
        
        return {
            "success": True,
            "file_path": output_path,
            "filename": filename,
            "format": output_format,
            "voice": voice,
            "model": model,
            "speed": speed,
            "text_length": len(text),
            "word_count": word_count,
            "duration_estimate_seconds": round(duration_estimate, 1),
            "file_size_bytes": file_size,
        }
        
    except Exception as e:
        logger.error(f"[TTS] Error: {e}", exc_info=True)
        return {"success": False, "error": f"TTS generation failed: {str(e)}"}


# ── Tool Schema for agent tools ──
TTS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "text_to_speech",
        "description": "Convert text to speech audio file. Supports multiple voices and formats. Use for generating audio narration, voice responses, or accessibility features.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to convert to speech (max 4096 characters)"
                },
                "voice": {
                    "type": "string",
                    "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                    "description": "Voice to use. alloy=neutral, echo=male, fable=expressive, onyx=deep, nova=female, shimmer=warm"
                },
                "output_format": {
                    "type": "string",
                    "enum": ["mp3", "opus", "aac", "flac", "wav"],
                    "description": "Audio output format. Default: mp3"
                },
                "speed": {
                    "type": "number",
                    "description": "Speech speed multiplier (0.25 to 4.0). Default: 1.0"
                }
            },
            "required": ["text"]
        }
    }
}
