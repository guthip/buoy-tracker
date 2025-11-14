from meshtastic_mqtt_json import MeshtasticMQTT

# Create client instance
client = MeshtasticMQTT()


# Register callbacks for specific message types
def on_nodeinfo(json_data):
    my_payload = json_data["decoded"]["payload"]
    print(f'Received nodeinfo message: {my_payload}')

def on_position(json_data):
    my_payload = json_data["decoded"]["payload"]
    print(f'Received position update: {my_payload}')

def on_telemetry(json_data):
    my_payload = json_data["decoded"]["payload"]
    print(f'Received telemetry update: {my_payload}')

def on_neigborinfo(json_data):
    my_payload = json_data["decoded"]["payload"]
    print(f'Received neigborinfo update: {my_payload}')



# the good stuff
client.register_callback('NODEINFO_APP', on_nodeinfo)
client.register_callback('POSITION_APP', on_position)

# the DUDS
client.register_callback('TELEMETRY_APP', on_telemetry)
client.register_callback('NEIGHBORINFO_APP', on_neigborinfo)



# Connect to MQTT broker
client.connect(
#    broker='mqtt.meshtastic.org',
#    port=1883,
#    root='msh/US/2/e/',
#    channel='LongFast',
     broker='mqtt.bayme.sh',
    port=1883,
    root='msh/US/bayarea/2/e/',
    channel='MediumFast',
    username='meshdev',
    password='large4cats',
    key='AQ=='
)

