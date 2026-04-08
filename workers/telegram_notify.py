"""Telegram notifications for task completion."""
import os
import logging
import httpx

logger = logging.getLogger("arcane.telegram")


async def notify(message: str, chat_id: str = None) -> bool:
    """Send Telegram notification. Returns True if sent."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not cid:
        return False
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": message, "parse_mode": "HTML"},
                timeout=5.0,
            )
        return True
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")
        return False
