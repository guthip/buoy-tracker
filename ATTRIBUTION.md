# Attribution & Open Source Libraries

Buoy Tracker is built upon the excellent work of the open source community. We are grateful for these projects.

## Direct Dependencies

### Core Libraries
- **[Meshtastic](https://meshtastic.org/)** - Open source mesh radio project providing the MQTT interface
  - License: GPL v3
  - Used for: Mesh network communication and packet decoding

- **[meshtastic-mqtt-json](https://github.com/meshtastic/python-mqtt-json)** - Python library for Meshtastic MQTT JSON parsing
  - License: GPL v3
  - Used for: MQTT packet handling and protocol decoding

- **[Flask](https://flask.palletsprojects.com/)** - Lightweight Python web framework
  - License: BSD 3-Clause
  - Used for: Web server and API endpoints

- **[Paho MQTT](https://github.com/eclipse/paho.mqtt.python)** - Python MQTT client
  - License: EPL v1.0 / EDL v1.0
  - Used for: MQTT broker communication

### Frontend Libraries
- **[Leaflet.js](https://leafletjs.com/)** - Interactive map library
  - License: BSD 2-Clause
  - Used for: Map rendering, markers, and GIS features

- **[OpenStreetMap](https://www.openstreetmap.org/)** - Free map tiles and data
  - License: ODbL 1.0 (Open Data Commons Open Database License)
  - Used for: Base map tile layer

- **[OpenSeaMap](https://www.openseamap.org/)** - Free nautical charts and marine data
  - License: CC-BY-SA 3.0 (Creative Commons Attribution-ShareAlike)
  - Used for: Overlay layer with worldwide seamarks, navigation marks, and depth contours
  - Coverage: Worldwide
  - Service: Seamark tile service at tiles.openseamap.org

### Optional Dependencies
- **[protobuf](https://github.com/protocolbuffers/protobuf)** - Protocol Buffers serialization
  - License: BSD 3-Clause
  - Used for: Message packet deserialization from Meshtastic

## Embedded Assets
- **Font Awesome** (via emoji) - For UI icons
  - License: CC BY 4.0 (for emoji/unicode)
  - Used for: Navigation and status indicators

## Development Tools
- **Python 3** - Programming language
  - License: PSF License (Python Software Foundation)

## License Compliance

Buoy Tracker respects the licenses of all dependencies:

- **GPL v3 components**: Meshtastic and meshtastic-mqtt-json require that any modifications or redistribution maintain GPL v3 compliance
- **BSD/MIT components**: Permissive licenses with minimal restrictions
- **ODbL for OpenStreetMap**: Map data used is under ODbL 1.0 (share-alike for data)
- **CC-BY-SA for OpenSeaMap**: Nautical chart data requires attribution and share-alike compliance

### Your Obligations

If you redistribute or modify Buoy Tracker, you must:

1. **Respect GPL v3 requirements** (for Meshtastic integration):
   - Keep source code available
   - Include license text
   - Document modifications
   - Apply same GPL v3 license to derivative works

2. **Maintain BSD/MIT attributions**:
   - Include license text in redistributions
   - Acknowledge the original authors

3. **Comply with ODbL for map data**:
   - If using OpenStreetMap tiles, acknowledge the data source
   - Share any derived/corrected map data under ODbL

## Recommended Open Source Standards

We recommend adopting these practices:

- **GPL v3** for derived works (strongest copyleft, ensures improvements benefit community)
- **MIT/BSD** for permissive libraries (encourage adoption and integration)
- **Apache 2.0** as an alternative to GPL v3 (includes explicit patent protection)

We encourage community contributions under GPL v3 terms.

## Questions?

For questions about licensing and attribution:
- See individual LICENSE files in dependencies
- Check the main [LICENSE](LICENSE) file for Buoy Tracker
- Review [README.md](README.md) for project overview
