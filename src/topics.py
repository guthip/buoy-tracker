"""MQTT topic parsing and display-text sanitization helpers."""

import logging

logger = logging.getLogger(__name__)

# Characters stripped from MQTT-sourced display text (node/channel names).
# Defense-in-depth against stored XSS — the web frontend also escapes at render time.
_UNSAFE_DISPLAY_CHARS = {ord(c): None for c in '<>"\''}


def sanitize_display_text(text):
    """Strip characters that could break out of HTML contexts from MQTT-sourced text."""
    if not isinstance(text, str):
        return text
    return text.translate(_UNSAFE_DISPLAY_CHARS)


def channel_from_topic(topic: str) -> str:
    """
    Extract channel name from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
    Returns channel name or "Unknown" if not found.
    """
    try:
        parts = topic.split('/')
        if 'e' in parts:
            e_idx = parts.index('e')
            if e_idx + 1 < len(parts):
                channel = parts[e_idx + 1]
                if not channel.startswith('!'):
                    return sanitize_display_text(channel)
    except Exception as e:
        logger.debug(f"Error extracting channel from topic {topic}: {e}")
    return "Unknown"


def gateway_id_from_topic(topic: str) -> int:
    """
    Extract the gateway node ID from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
    The node ID after the '!' is the gateway that the message came through.
    Returns the node ID (int) or None if not found.
    """
    try:
        parts = topic.split('/')
        for part in parts:
            if part.startswith('!'):
                hex_id = part[1:]
                return int(hex_id, 16)
    except Exception as e:
        logger.debug(f"Error extracting gateway node ID from topic {topic}: {e}")
    return None
