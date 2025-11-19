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
        # Don't send more than once per cooldown period
        if time_since_last < config.ALERT_COOLDOWN:
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
        battery = node_data.get('battery_level', 'Unknown')
        
        # Special node label
        special_label = config.SPECIAL_NODES.get(node_id, {}).get('label', node_name)
        
        # Create email
        subject = f"🚨 {config.APP_TITLE} - Movement Alert: {special_label}"
        
        body = f"""{config.APP_TITLE} - Movement Alert

ALERT TYPE: Position Outside Safe Zone

Buoy: {special_label}

DETECTION TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

ALERT DETAILS:
  Distance from home: {distance_m:.0f} meters
  Safe zone threshold: {config.SPECIAL_MOVEMENT_THRESHOLD_METERS} meters

TELEMETRY:
  Battery Level: {battery}%

VIEW ON TRACKER: {config.ALERT_TRACKER_URL if hasattr(config, 'ALERT_TRACKER_URL') else 'http://localhost:5102'}

---
This is an automated alert from {config.APP_TITLE}.
Alert cooldown: {config.ALERT_COOLDOWN}s (next alert after this time)
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


def send_battery_alert(node_id, node_data, battery_level):
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
            logger.debug(f"Skipping battery alert for {node_id}, last sent {time_since_last:.0f}s ago")
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
        
        # Special node label
        special_label = config.SPECIAL_NODES.get(node_id, {}).get('label', node_name)
        
        # Create email
        subject = f"🔋 {config.APP_TITLE} - Low Battery Alert: {special_label}"
        
        body = f"""{config.APP_TITLE} - Low Battery Alert

ALERT TYPE: Low Battery Level

Buoy: {special_label}

DETECTION TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

ALERT DETAILS:
  Current battery: {battery_level}%

VIEW ON TRACKER: {config.ALERT_TRACKER_URL if hasattr(config, 'ALERT_TRACKER_URL') else 'http://localhost:5102'}

---
This is an automated alert from {config.APP_TITLE}.
Alert cooldown: {config.ALERT_COOLDOWN / 3600:.1f} hours between alerts
"""
        
        # Send email
        _send_email(
            to_addresses=config.ALERT_EMAIL_TO,
            subject=subject,
            body=body
        )
        
        # Update last sent time
        last_alert_sent[alert_key] = now
        logger.info(f"Sent battery alert for {special_label} ({battery_level}%)")
        
    except Exception as e:
        logger.error(f"Failed to send battery alert: {e}", exc_info=True)


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
    
    # Send email via SMTP
    # Support for both authenticated SMTP (Google, SendGrid, etc.) and local sendmail (localhost:25)
    use_auth = config.ALERT_SMTP_USERNAME and config.ALERT_SMTP_PASSWORD
    
    if config.ALERT_SMTP_SSL:
        # Use SSL (typically port 465)
        with smtplib.SMTP_SSL(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10) as server:
            if use_auth:
                server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
            server.send_message(msg)
    else:
        # Use plain SMTP or STARTTLS (typically port 25 for sendmail or 587 for external providers)
        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10) as server:
            # Only use STARTTLS if not localhost (sendmail doesn't need it)
            if config.ALERT_SMTP_HOST != 'localhost':
                server.starttls()
            if use_auth:
                server.login(config.ALERT_SMTP_USERNAME, config.ALERT_SMTP_PASSWORD)
            server.send_message(msg)
    
    logger.info(f"Email sent to {to_addresses}")


def test_email_config():
    """Test email configuration by sending a test message."""
    try:
        # Convert cooldown seconds to hours for display
        cooldown_hours = config.ALERT_COOLDOWN / 3600
        
        _send_email(
            to_addresses=config.ALERT_EMAIL_TO,
            subject=f"{config.APP_TITLE} - Test Email",
            body=f"""
{config.APP_TITLE} - Test Email Configuration

This is a test email from {config.APP_TITLE}.

If you received this, email alerts are configured correctly!

Alert Cooldown: {cooldown_hours:.1f} hours between alerts

Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
This is an automated test email from {config.APP_TITLE}.
"""
        )
        logger.info("Test email sent successfully")
        return True
    except Exception as e:
        logger.error(f"Test email failed: {e}", exc_info=True)
        return False
