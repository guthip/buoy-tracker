#!/usr/bin/env python3
import meshtastic.mesh_pb2 as mesh_pb2
import meshtastic.mqtt_pb2 as mqtt_pb2
import meshtastic.portnums_pb2 as portnums_pb2

print("=== MQTT Message Structure ===")
sm = mqtt_pb2.ServiceEnvelope()
print("ServiceEnvelope fields:")
for field in sm.DESCRIPTOR.fields:
    print(f"  - {field.name}: {field.type}")

print("\n=== MeshPacket Structure ===")
mp = mesh_pb2.MeshPacket()
print("MeshPacket fields:")
for field in mp.DESCRIPTOR.fields:
    print(f"  - {field.name}")

print("\n=== Data Structure ===")
data = mesh_pb2.Data()
print("Data fields:")
for field in data.DESCRIPTOR.fields:
    print(f"  - {field.name}")

print("\n=== PortNum values (app types) ===")
print("POSITION_APP:", portnums_pb2.POSITION_APP)
print("NODEINFO_APP:", portnums_pb2.NODEINFO_APP)
print("TELEMETRY_APP:", portnums_pb2.TELEMETRY_APP)
