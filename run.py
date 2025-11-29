#!/usr/bin/env python3
"""Simple runner for the Buoy Tracker Flask app"""

import sys
import os
import socket
import signal

# Ensure working directory is the project root (where this script is located)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

# Suppress Flask development server warning
os.environ['WERKZEUG_RUN_MAIN'] = 'true'

def signal_handler(signum, frame):
    """Handle signals gracefully."""
    print(f'Received signal {signum}, shutting down...', flush=True)
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

try:
    print('[STARTUP] Importing modules...', flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    
    from src.main import app, init_background_services
    from src import config
    from werkzeug.serving import make_server

    print(f'[STARTUP] Modules imported successfully', flush=True)
    print(f'[STARTUP] Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}', flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

    print(f'[STARTUP] Creating server...', flush=True)

    # Start background services (MQTT thread)
    print('[DEBUG] [RUN.PY] Calling init_background_services() to start MQTT thread...', flush=True)
    init_background_services()
    print('[DEBUG] [RUN.PY] Returned from init_background_services()', flush=True)

    server = make_server(
        config.WEBAPP_HOST,
        config.WEBAPP_PORT,
        app,
        threaded=True
    )

    # Enable SO_REUSEADDR to allow immediate restart
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

    print(f'[STARTUP] Server created and socket configured', flush=True)
    print(f'[STARTUP] Starting serve_forever()...', flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

    server.serve_forever()
    
except KeyboardInterrupt:
    print(f'[SHUTDOWN] Keyboard interrupt received', flush=True)
    sys.exit(0)
    
except SystemExit as e:
    print(f'[SHUTDOWN] System exit: {e}', flush=True)
    sys.exit(e.code if hasattr(e, 'code') else 1)
    
except Exception as e:
    print(f'[FATAL ERROR] {type(e).__name__}: {e}', flush=True)
    import traceback
    traceback.print_exc()
    sys.stderr.flush()
    sys.exit(1)
