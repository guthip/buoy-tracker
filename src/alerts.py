"""Email alert system for movement notifications"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from . import config

logger = logging.getLogger(__name__)

# Track when we last sent alerts to avoid spamming
last_alert_sent = {}  # node_id -> timestamp

def send_movement_alert(node_id, node_data, distance_m):
    """
    Send email alert when a special node moves beyond threshold.
    
    Args:
        node_id: Node ID that moved
        node_data: Dictionary with node information
        distance_m: Distance from origin in meters
    """
    # Check if we should send alert (avoid spam)
    import time
    now = time.time()
    if node_id in last_alert_sent:
        time_since_last = now - last_alert_sent[node_id]
        # Don't send more than once per hour
        if time_since_last < 3600:
            logger.debug(f"Skipping alert for {node_id}, last sent {time_since_last:.0f}s ago")
            return
    
    try:
        # Get alert configuration
        if not hasattr(config, 'ALERT_ENABLED') or not config.ALERT_ENABLED:
            logger.debug("Email alerts disabled in config")
            return
        
        # Get node details
        node_name = node_data.get('long_name', 'Unknown')
        short_name = node_data.get('short_name', '?')
        lat = node_data.get('latitude')
        lon = node_data.get('longitude')
        origin_lat = node_data.get('origin_lat')
        origin_lon = node_data.get('origin_lon')
        
        # Special node label
        special_label = config.SPECIAL_NODES.get(node_id, {}).get('label', node_name)
        
        # Create email
        subject = f"⚠️ Movement Alert: {special_label} moved {distance_m:.0f}m from home"
        
        body = f"""
Movement Alert - Buoy Tracker

Node: {special_label} ({node_name})
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

ALERT: Node has moved {distance_m:.0f} meters from its home position
Threshold: {config.SPECIAL_MOVEMENT_THRESHOLD_METERS}m

Current Position:
  Latitude: {lat:.6f}
  Longitude: {lon:.6f}
  Map: https://www.google.com/maps?q={lat},{lon}

Home Position:
  Latitude: {origin_lat:.6f}
  Longitude: {origin_lon:.6f}
  Map: https://www.google.com/maps?q={origin_lat},{origin_lon}

Tracker: {config.ALERT_TRACKER_URL if hasattr(config, 'ALERT_TRACKER_URL') else 'http://localhost:5101'}

---
This is an automated alert from Buoy Tracker.
"""
        
        # Send email
        _send_email(
            to_addresses=config.ALERT_EMAIL_TO,
            subject=subject,
            body=body
        )
        
        # Update last sent time
        last_alert_sent[node_id] = now
        logger.info(f"Sent movement alert for {special_label} ({distance_m:.0f}m)")
        
    except Exception as e:
        logger.error(f"Failed to send movement alert: {e}", exc_info=True)


def _send_email(to_addresses, subject, body):
    """
    Send email using SMTP.
    
    Args:
        to_addresses: List of email addresses or single string
        subject: Email subject
        body: Email body (plain text)
    """
    # Normalize to list
    if isinstance(to_addresses, str):
        to_addresses = [addr.strip() for addr in to_addresses.split(',')]
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config.ALERT_EMAIL_FROM
    msg['To'] = ', '.join(to_addresses)
    
    # Add plain text body
    msg.attach(MIMEText(body, 'plain'))
    
    # Send email
    if config.ALERT_SMTP_SSL:
        # Use SSL
        with smtplib.SMTP_SSL(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT) as server:
            if config.ALERT_SMTP_USERNAME and config.ALERT_SMTP_PASSWORD:
                server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
            server.send_message(msg)
    else:
        # Use STARTTLS
        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT) as server:
            server.starttls()
            if config.ALERT_SMTP_USERNAME and config.ALERT_SMTP_PASSWORD:
                server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
            server.send_message(msg)
    
    logger.info(f"Email sent to {to_addresses}")


def test_email_config():
    """Test email configuration by sending a test message."""
    try:
        _send_email(
            to_addresses=config.ALERT_EMAIL_TO,
            subject="Buoy Tracker - Test Email",
            body=f"""
This is a test email from Buoy Tracker.

Configuration:
  SMTP Host: {config.ALERT_SMTP_HOST}
  SMTP Port: {config.ALERT_SMTP_PORT}
  From: {config.ALERT_EMAIL_FROM}
  To: {config.ALERT_EMAIL_TO}
  SSL: {config.ALERT_SMTP_SSL}

If you received this, email alerts are configured correctly!

Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        )
        logger.info("Test email sent successfully")
        return True
    except Exception as e:
        logger.error(f"Test email failed: {e}", exc_info=True)
        return False
