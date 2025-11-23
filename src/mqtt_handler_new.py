"""
Meshtastic MQTT Handler for Buoy Tracker - Pure paho-mqtt implementation
Directly uses paho-mqtt to receive and decode Meshtastic protocol buffer messages.
Extracts channel names from MQTT topic paths.
"""

import paho.mqtt.client as mqtt_client
import base64
import json
import time
import logging
import re
from collections import deque
from pathlib import Path
from . import config
from . import alerts
import os
import math
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Import Meshtastic protobuf definitions
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2

logger = logging.getLogger(__name__)

# MQTT client
client = None

# Dictionary to store node data: {node_id: {name, long_name, position, telemetry, last_seen}}
nodes_data = {}
# Ring buffer for recent raw messages for debugging
recent_messages = deque(maxlen=config.RECENT_MESSAGE_BUFFER_SIZE)
# Track if we've received any messages
message_received = False
packets_received = False
last_message_time = 0

# Special nodes history: node_id -> deque of {ts, lat, lon, alt}
special_history = {}
_last_history_save = 0

# Special nodes packet tracking: store ALL packets for special nodes
special_node_packets = {}
special_node_last_packet = {}
special_node_channels = {}
special_node_position_timestamps = {}
_last_channel_save = 0
_last_packet_save = 0


def _is_special_node(node_id):
    """Check if a node_id is in the special nodes list."""
    return node_id in config.SPECIAL_NODES


# ... [rest of helper functions will be the same as mqtt_handler.py] ...


def extract_channel_from_topic(topic: str) -> str:
    """
    Extract channel name from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
    """
    try:
        parts = topic.split('/')
        if 'e' in parts:
            e_idx = parts.index('e')
            if e_idx + 1 < len(parts):
                channel = parts[e_idx + 1]
                # Make sure it's not a node id part (starts with !)
                if not channel.startswith('!'):
                    return channel
    except Exception as e:
        logger.debug(f"Error extracting channel from topic {topic}: {e}")
    
    return "Unknown"


def decrypt_message_packet(mp, key_bytes):
    """
    Decrypt an encrypted Meshtastic message packet.
    Uses AES-CTR with nonce derived from packet ID and sender ID.
    """
    try:
        # Extract the nonce from the packet
        nonce_packet_id = getattr(mp, 'id').to_bytes(8, 'little')
        nonce_from_node = getattr(mp, 'from').to_bytes(8, 'little')
        nonce = nonce_packet_id + nonce_from_node

        # Decrypt the message
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(mp, 'encrypted')) + decryptor.finalize()
        
        # Parse the decrypted message
        data = mesh_pb2.Data()
        try:
            data.ParseFromString(decrypted_bytes)
        except:
            return None

        mp.decoded.CopyFrom(data)
        return mp

    except Exception as e:
        logger.debug(f'Error decrypting message: {e}')
        return None


def convert_protobuf_to_json(proto_obj):
    """
    Convert a protobuf message to JSON-serializable dict.
    Handles NaN values by removing them.
    """
    from google.protobuf.json_format import MessageToJson
    
    try:
        json_str = MessageToJson(proto_obj, preserving_proto_field_name=True)
        data = json.loads(json_str)
        
        # Remove empty values and NaN
        def clean_dict(d):
            if isinstance(d, dict):
                return {k: clean_dict(v) for k, v in d.items() if str(v) not in ('None', 'nan', '', 'null')}
            elif isinstance(d, list):
                return [clean_dict(v) for v in d if str(v) not in ('None', 'nan', '')]
            return d
        
        return clean_dict(data)
    except Exception as e:
        logger.debug(f"Error converting protobuf to JSON: {e}")
        return {}


def on_mqtt_message(client_obj, userdata, msg):
    """
    Main MQTT message callback - receives raw encoded messages.
    Decodes ServiceEnvelope protobuf, handles decryption, routes to handlers.
    """
    global message_received, last_message_time, packets_received
    
    try:
        # Extract channel from topic path
        channel_name = extract_channel_from_topic(msg.topic)
        
        # Parse MQTT ServiceEnvelope protobuf
        service_envelope = mqtt_pb2.ServiceEnvelope()
        try:
            service_envelope.ParseFromString(msg.payload)
        except Exception as e:
            logger.debug(f"Error parsing ServiceEnvelope: {e}")
            return
        
        # Extract MeshPacket from envelope
        mp = service_envelope.packet
        
        # Handle encrypted packets
        if mp.HasField('encrypted'):
            mp = decrypt_message_packet(mp, userdata['key_bytes'])
            if not mp:
                return
        
        # Extract portnum (message type)
        portnum = mp.decoded.portnum
        portnum_name = portnums_pb2.PortNum.Name(portnum)
        
        # Convert to JSON for callbacks
        json_packet = convert_protobuf_to_json(mp)
        
        # Add channel name to packet data
        if 'decoded' not in json_packet:
            json_packet['decoded'] = {}
        json_packet['channel_name'] = channel_name
        
        # Store in recent messages buffer
        recent_messages.append(json_packet)
        
        # Mark as received
        message_received = True
        packets_received = True
        last_message_time = time.time()
        
        # Route to appropriate handler based on message type
        route_message(portnum, portnum_name, mp, json_packet)
        
    except Exception as e:
        logger.error(f"Error in MQTT message handler: {e}", exc_info=True)


def route_message(portnum, portnum_name, mp, json_packet):
    """Route decoded message to appropriate handler based on message type."""
    # Extract payload based on message type
    if portnum == portnums_pb2.ADMIN_APP:
        data = mesh_pb2.Admin()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
    
    elif portnum == portnums_pb2.POSITION_APP:
        data = mesh_pb2.Position()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
        on_position(json_packet)
        return
    
    elif portnum == portnums_pb2.NODEINFO_APP:
        data = mesh_pb2.User()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
        on_nodeinfo(json_packet)
        return
    
    elif portnum == portnums_pb2.TELEMETRY_APP:
        data = telemetry_pb2.Telemetry()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
        on_telemetry(json_packet)
        return
    
    elif portnum == portnums_pb2.MAP_REPORT_APP:
        data = mesh_pb2.MapReport()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
        on_mapreport(json_packet)
        return
    
    elif portnum == portnums_pb2.NEIGHBORINFO_APP:
        data = mesh_pb2.NeighborInfo()
        data.ParseFromString(mp.decoded.payload)
        json_packet['decoded']['payload'] = convert_protobuf_to_json(data)
        on_neighborinfo(json_packet)
        return
    
    # For other message types, log but don't crash
    logger.debug(f"Received message type: {portnum_name}")


# Include all the existing handler functions here
# (on_position, on_telemetry, on_nodeinfo, etc.)
# For now, just import them from the existing handler...

def on_position(json_data):
    """Process position messages - update node coordinates."""
    # This will be imported or moved from existing mqtt_handler
    pass


def on_telemetry(json_data):
    """Process telemetry messages - battery level, etc."""
    pass


def on_nodeinfo(json_data):
    """Process node info messages - update node names."""
    pass


def on_neighborinfo(json_data):
    """Process neighbor info messages."""
    pass


def on_mapreport(json_data):
    """Process map report messages."""
    pass


def connect_mqtt():
    """Connect to MQTT broker and start message loop."""
    global client
    
    try:
        # Create paho-mqtt client
        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id='',
            clean_session=True,
            userdata=None
        )
        client.connect_timeout = 10
        
        # Set credentials
        if config.MQTT_USERNAME:
            client.username_pw_set(
                username=config.MQTT_USERNAME,
                password=config.MQTT_PASSWORD
            )
        
        # Prepare encryption key
        key_str = getattr(config, 'MQTT_KEY', 'AQ==')
        if key_str == 'AQ==':
            key_str = '1PG7OiApB1nwvP+rz05pAQ=='
        
        # Decode and pad base64 key
        padded_key = key_str.ljust(len(key_str) + ((4 - (len(key_str) % 4)) % 4), '=')
        replaced_key = padded_key.replace('-', '+').replace('_', '/')
        key_bytes = base64.b64decode(replaced_key.encode('ascii'))
        
        # Set callbacks and userdata
        client.on_message = on_mqtt_message
        client.user_data_set({'key_bytes': key_bytes})
        
        # Connect to broker
        logger.info(f"Connecting to MQTT broker: {config.MQTT_BROKER}:{config.MQTT_PORT}")
        client.connect(config.MQTT_BROKER, config.MQTT_PORT, 60)
        
        # Subscribe to root topic with wildcard to get all channels
        root_topic = config.MQTT_ROOT_TOPIC.rstrip('/') + '/#'
        logger.info(f"Subscribing to: {root_topic}")
        client.subscribe(root_topic)
        
        # Start the loop
        logger.info("Starting MQTT loop")
        client.loop_start()
        
        logger.info("✅ MQTT client connected and ready")
        
    except Exception as e:
        logger.error(f"Failed to connect to MQTT: {e}", exc_info=True)
        client = None
        raise


def disconnect_mqtt():
    """Disconnect from MQTT broker."""
    global client
    try:
        if client:
            client.loop_stop()
            client.disconnect()
            logger.info("Disconnected from MQTT broker")
    except Exception as e:
        logger.error(f"Error disconnecting from MQTT: {e}")


def is_connected():
    """Check if MQTT client is connected."""
    global message_received
    # Consider connected if we've received messages recently
    if message_received and (time.time() - last_message_time) < 300:  # 5 min timeout
        return True
    return False
