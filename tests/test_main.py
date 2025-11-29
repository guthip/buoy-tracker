"""
Tests for the main application module.
"""

import pytest
from unittest.mock import patch
from src import config
from src.main import app


@pytest.fixture
def client():
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_headers():
    """Provide valid auth headers."""
    api_key = config.API_KEY or 'test-key-12345'
    return {'Authorization': f'Bearer {api_key}'}


@patch('src.main.mqtt_handler')
def test_health_check(mock_mqtt, client):
    """Test the health check endpoint (no auth required)."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'ok'


@patch('src.main.mqtt_handler')
def test_get_nodes(mock_mqtt, client, auth_headers):
    """Test the get nodes endpoint (requires auth)."""
    mock_mqtt.get_nodes.return_value = []
    response = client.get('/api/nodes', headers=auth_headers, environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 200
    assert 'nodes' in response.json
    assert 'count' in response.json


@patch('src.main.mqtt_handler')
def test_get_api_status(mock_mqtt, client, auth_headers):
    """Test the API status endpoint (requires auth)."""
    mock_mqtt.is_connected.return_value = 'connected'
    mock_mqtt.get_nodes.return_value = []
    response = client.get('/api/status', headers=auth_headers, environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 200
    assert 'mqtt_connected' in response.json
    assert 'nodes_tracked' in response.json


@patch('src.main.mqtt_handler')
def test_index_page(mock_mqtt, client):
    """Test the index page returns HTML (no auth required)."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'html' in response.data.lower()


def test_404_not_found(client):
    """Test 404 error handling."""
    # Use a path that does not match any route and is not OPTIONS
    response = client.get('/this-path-does-not-exist-xyz', environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 404
