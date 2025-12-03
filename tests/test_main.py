"""
Tests for the main application module.
"""

import pytest
from unittest.mock import patch, MagicMock
from src import config
from src.main import app


@pytest.fixture
def mock_mqtt():
    """Mock the MQTT handler."""
    with patch('src.main.mqtt_handler') as mock:
        mock.is_connected.return_value = 'connected'
        mock.get_nodes.return_value = []
        mock.get_recent.return_value = []
        mock.get_special_history.return_value = []
        mock.get_special_node_packets.return_value = {}
        yield mock


@pytest.fixture
def client(mock_mqtt):
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_headers():
    """Provide valid auth headers."""
    api_key = config.API_KEY or 'test-key-12345'
    return {'Authorization': f'Bearer {api_key}'}


def test_health_check(client, mock_mqtt):
    """Test the health check endpoint (no auth required)."""
    response = client.get('/health')
    assert response.status_code == 200
    data = response.get_json() or response.json
    assert data['status'] == 'ok'


def test_get_nodes(client, auth_headers, mock_mqtt):
    """Test the get nodes endpoint (requires auth)."""
    mock_mqtt.get_nodes.return_value = []
    response = client.get('/api/nodes', headers=auth_headers, environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 200
    data = response.get_json() or response.json
    assert 'nodes' in data
    assert 'count' in data


def test_get_health(client, auth_headers, mock_mqtt):
    """Test the health endpoint (requires auth)."""
    mock_mqtt.is_connected.return_value = 'connected'
    mock_mqtt.get_nodes.return_value = []
    response = client.get('/health', headers=auth_headers, environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 200
    data = response.get_json() or response.json
    assert 'mqtt_connected' in data
    assert 'nodes_tracked' in data


def test_index_page(client, mock_mqtt):
    """Test the index page returns HTML (no auth required)."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'html' in response.data.lower()


def test_404_not_found(client, mock_mqtt):
    """Test 404 error handling."""
    # Use a path that does not match any route and is not OPTIONS
    response = client.get('/this-path-does-not-exist-xyz', environ_base={'REMOTE_ADDR': '192.168.1.100'})
    assert response.status_code == 404
