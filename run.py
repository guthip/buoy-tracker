#!/usr/bin/env python3
"""Simple runner for the Buoy Tracker Flask app"""
import sys
import os
import signal
import subprocess
sys.path.insert(0, '.')
from src.main import app
from src import config

def kill_port_process(port):
    """Kill any process occupying the specified port."""
    try:
        # Find process using the port
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f'Killed process {pid} on port {port}')
                except ProcessLookupError:
                    pass  # Process already dead
                except Exception as e:
                    print(f'Warning: Could not kill process {pid}: {e}')
    except FileNotFoundError:
        # lsof not available, try netstat approach (less reliable)
        pass
    except Exception as e:
        print(f'Warning: Port cleanup failed: {e}')

if __name__ == '__main__':
    # Clean up any existing process on our port
    kill_port_process(config.WEBAPP_PORT)
    
    print(f'Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}')
    app.run(host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, debug=False, threaded=True)
