"""
Tests for the main application module.
"""

import pytest
from src.main import app


@pytest.fixture
def client():
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'ok'


def test_get_nodes(client):
    """Test the get nodes endpoint."""
    response = client.get('/api/nodes')
    assert response.status_code == 200
    assert 'nodes' in response.json
    assert 'count' in response.json


def test_get_mqtt_status(client):
    """Test the MQTT status endpoint."""
    response = client.get('/api/mqtt/status')
    assert response.status_code == 200
    assert 'connected' in response.json


def test_get_api_status(client):
    """Test the API status endpoint."""
    response = client.get('/api/status')
    assert response.status_code == 200
    assert 'mqtt_connected' in response.json
    assert 'nodes_tracked' in response.json


def test_index_page(client):
    """Test the index page returns HTML."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'html' in response.data.lower()


def test_404_not_found(client):
    """Test 404 error handling."""
    response = client.get('/nonexistent')
    assert response.status_code == 404
