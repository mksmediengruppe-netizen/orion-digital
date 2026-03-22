"""
MEGA PATCH Bug 3.7: Opus emergency escalation tracker
"""
import logging

logger = logging.getLogger("opus_escalation")

_rejection_counts = {}


def check_opus_escalation(chat_id, rejected):
    """Track rejections and escalate to Opus after 2 consecutive rejections.
    Returns True if should escalate to Opus."""
    if rejected:
        _rejection_counts[chat_id] = _rejection_counts.get(chat_id, 0) + 1
        if _rejection_counts[chat_id] >= 2:
            logger.warning(
                f"Chat {chat_id}: {_rejection_counts[chat_id]} rejections, "
                "escalating to Opus for replanning"
            )
            _rejection_counts[chat_id] = 0
            return True
    else:
        _rejection_counts[chat_id] = 0
    return False


def reset_rejection_count(chat_id):
    """Reset rejection counter for a chat."""
    _rejection_counts.pop(chat_id, None)
