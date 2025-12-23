"""Email alert system for movement notifications"""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Union, Any

from . import config

logger = logging.getLogger(__name__)

# Track when we last sent alerts to avoid spamming
# Pruned periodically to prevent memory leak
last_alert_sent = {}  # node_id -> timestamp


def _cleanup_alert_history() -> None:
    """Remove stale alert records for nodes that no longer exist or are too old."""
    import time
    try:
        now = time.time()
        # Remove alerts older than 3x the cooldown period (shouldn't accumulate beyond this)
        max_age = config.ALERT_COOLDOWN * 3
        cutoff_time = now - max_age
        
        # Remove dead node IDs and overly old entries
        to_remove = [
            node_id for node_id, timestamp in last_alert_sent.items()
            if node_id not in config.SPECIAL_NODE_IDS or timestamp < cutoff_time
        ]
        
        for node_id in to_remove:
            del last_alert_sent[node_id]
        
        if to_remove:
            logger.debug(f'Cleaned up {len(to_remove)} stale alert records')
    except Exception as e:
        logger.warning(f'Error cleaning up alert history: {e}')


def send_movement_alert(node_id: int, node_data: Dict[str, Any], distance_m: float) -> None:
    """
    Send email alert when a special node moves beyond threshold.

    Args:
        node_id: Node ID that moved
        node_data: Dictionary with node information
        distance_m: Distance from origin in meters
    """
    # Periodically clean up old alert records
    _cleanup_alert_history()
    
    # Check if we should send alert (avoid spam)
    import time

    now = time.time()
    if node_id in last_alert_sent:
        time_since_last = now - last_alert_sent[node_id]
        # Don't send more than once per cooldown period
        if time_since_last < config.ALERT_COOLDOWN:
            logger.debug(
                f"Skipping alert for node_id {node_id}, last sent {int(time_since_last)}s ago"
            )
            return

    try:
        # Get alert configuration
        if not hasattr(config, "ALERT_ENABLED") or not config.ALERT_ENABLED:
            logger.debug("Email alerts disabled in config")
            return

        # Get node details
        node_name = node_data.get("long_name", "Unknown")
        battery = node_data.get("battery_level", node_data.get("battery", "Unknown"))

        # Special node label
        special_label = config.SPECIAL_NODES.get(node_id, {}).get("label", node_name)

        # Create email
        subject = f"🚨 {config.APP_TITLE} - Movement Alert: {special_label}"

        body = (
            f"{config.APP_TITLE} - Movement Alert\n\n"
            f"ALERT TYPE: Position Outside Safe Zone\n\n"
            f"Buoy: {special_label}\n\n"
            f"DETECTION TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            f"ALERT DETAILS:\n  Distance from home: {int(distance_m)} meters\n  Safe zone threshold: {config.SPECIAL_MOVEMENT_THRESHOLD_METERS} meters\n\n"
            f"TELEMETRY:\n  Battery Level: {battery}%\n\n"
            f"VIEW ON TRACKER: {getattr(config, 'ALERT_TRACKER_URL', 'http://localhost:5103')}\n\n"
            f"---\nThis is an automated alert from {config.APP_TITLE}.\nAlert cooldown: {config.ALERT_COOLDOWN}s (next alert after this time)"
        )

        # Send email
        _send_email(to_addresses=config.ALERT_EMAIL_TO, subject=subject, body=body)

        # Update last sent time
        last_alert_sent[node_id] = now
        logger.info(f"Sent movement alert for {special_label} ({int(distance_m)}m)")

    except Exception as e:
        logger.error(f"Failed to send movement alert: {e}", exc_info=True)


def send_battery_alert(node_id: int, node_data: Dict[str, Any], battery_level: int) -> None:
    """
    Send email alert when a special node has low battery.

    Args:
        node_id: Node ID with low battery
        node_data: Dictionary with node information
        battery_level: Current battery percentage
    """
    # Check if we should send alert (avoid spam)
    import time

    now = time.time()
    alert_key = f"{node_id}_battery"
    if alert_key in last_alert_sent:
        time_since_last = now - last_alert_sent[alert_key]
        # Don't send more than once per cooldown period
        if time_since_last < config.ALERT_COOLDOWN:
            logger.debug(
                f"Skipping battery alert for node_id {node_id}, last sent {int(time_since_last)}s ago"
            )
            return

    try:
        # Get alert configuration
        if not hasattr(config, "ALERT_ENABLED") or not config.ALERT_ENABLED:
            logger.debug("Email alerts disabled in config")
            return

        # Get node details
        node_name = node_data.get("long_name", "Unknown")

        # Special node label
        special_label = config.SPECIAL_NODES.get(node_id, {}).get("label", node_name)

        # Create email
        subject = f"🔋 {config.APP_TITLE} - Low Battery Alert: {special_label}"

        body = (
            f"{config.APP_TITLE} - Low Battery Alert\n\n"
            f"ALERT TYPE: Low Battery Level\n\n"
            f"Buoy: {special_label}\n\n"
            f"DETECTION TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            f"ALERT DETAILS:\n  Current battery: {battery_level}%\n\n"
            f"VIEW ON TRACKER: {getattr(config, 'ALERT_TRACKER_URL', 'http://localhost:5103')}\n\n"
            f"---\nThis is an automated alert from {config.APP_TITLE}.\nAlert cooldown: {config.ALERT_COOLDOWN / 3600:.1f} hours between alerts"
        )

        # Send email
        _send_email(to_addresses=config.ALERT_EMAIL_TO, subject=subject, body=body)

        # Update last sent time
        last_alert_sent[alert_key] = now
        logger.info(f"Sent battery alert for {special_label} ({battery_level}%)")

    except Exception as e:
        logger.error(f"Failed to send battery alert: {e}", exc_info=True)


def _send_email(to_addresses: Union[str, List[str]], subject: str, body: str) -> None:
    """
    Send email using SMTP.

    Args:
        to_addresses: List of email addresses or single string
        subject: Email subject
        body: Email body (plain text)
    """
    # Normalize to list
    if isinstance(to_addresses, str):
        to_addresses = [addr.strip() for addr in to_addresses.split(",")]

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.ALERT_EMAIL_FROM
    msg["To"] = ", ".join(to_addresses)

    # Add plain text body
    msg.attach(MIMEText(body, "plain"))

    # Send email via SMTP
    use_auth = bool(getattr(config, "ALERT_SMTP_USERNAME", None)) and bool(
        getattr(config, "ALERT_SMTP_PASSWORD", None)
    )

    try:
        if getattr(config, "ALERT_SMTP_SSL", False):
            # Use SSL (typically port 465)
            with smtplib.SMTP_SSL(
                config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10
            ) as server:
                if use_auth:
                    server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # Use plain SMTP or STARTTLS (typically port 25 for sendmail or 587 for external providers)
            with smtplib.SMTP(
                config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10
            ) as server:
                # Only use STARTTLS if not localhost (sendmail doesn't need it)
                if config.ALERT_SMTP_HOST != "localhost":
                    server.starttls()
                if use_auth:
                    server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
                server.send_message(msg)
            logger.info(f"Email sent to {to_addresses}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}", exc_info=True)
