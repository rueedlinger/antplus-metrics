# tests/test_api.py
import asyncio

import pytest
import json
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock, patch

from app.api import app, shutdown_event
from app.model import MetricsModel, MetricsSettingsModel


@pytest.fixture
async def client():
    await app.router.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    await app.router.shutdown()


# -------------------------
# Retry tests for /metrics/start
# -------------------------
@patch("app.api.Metrics")
async def test_metrics_start_retry_success(mock_metrics_class, client):
    mock_metrics = MagicMock()
    mock_metrics.start.side_effect = [Exception("fail1"), Exception("fail2"), None]
    mock_metrics_class.return_value = mock_metrics
    app.state.metrics = mock_metrics

    response = await client.post("/metrics/start")
    assert response.status_code == 200
    assert "started" in response.json()["message"]
    assert mock_metrics.start.call_count == 3


@patch("app.api.Metrics")
async def test_metrics_start_retry_fail(mock_metrics_class, client):
    mock_metrics = MagicMock()
    mock_metrics.start.side_effect = Exception("always fails")
    mock_metrics_class.return_value = mock_metrics
    app.state.metrics = mock_metrics

    response = await client.post("/metrics/start")
    assert response.status_code == 500
    assert "Failed to start metrics after" in response.json()["detail"]
    assert mock_metrics.start.call_count == 3


# -------------------------
# Metrics settings tests
# -------------------------
@patch("app.api.Metrics")
async def test_update_metrics_settings(mock_metrics_class, client):
    mock_metrics = MagicMock()
    mock_metrics.set_metrics_settings.return_value = None
    mock_metrics.get_metrics_settings.return_value = MetricsSettingsModel(
        age=30, speed_wheel_circumference_m=0.15, distance_wheel_circumference_m=0.14
    )
    mock_metrics_class.return_value = mock_metrics
    app.state.metrics = mock_metrics

    payload = {
        "age": 25,
        "speed_wheel_circumference_m": 0.141,
        "distance_wheel_circumference_m": 0.141,
    }

    response = await client.post("/metrics/settings", json=payload)
    assert response.status_code == 200
    assert "updated" in response.json()["message"]
    mock_metrics.set_metrics_settings.assert_called_once()

    response = await client.get("/metrics/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["age"] == 30
    assert data["speed_wheel_circumference_m"] == 0.15
    assert data["distance_wheel_circumference_m"] == 0.14


# -------------------------
# GET /metrics
# -------------------------
@patch("app.api.Metrics")
async def test_get_metrics(mock_metrics_class, client):
    mock_metrics = MagicMock()
    mock_metrics.get_metrics.return_value = MetricsModel(
        power=100,
        ma_power=95,
        speed=5.5,
        ma_speed=5.2,
        cadence=80,
        ma_cadence=78,
        distance=1200,
        ma_distance=1180,
        heart_rate=140,
        ma_heart_rate=138,
        heart_rate_percent=75,
        ma_heart_rate_percent=74,
        zone_name="MODERATE",
        ma_zone_name="MODERATE",
        zone_description="Moderate intensity",
        ma_zone_description="Moderate intensity",
        is_running=True,
        last_sensor_update=None,
        last_sensor_name=None,
    )
    mock_metrics_class.return_value = mock_metrics
    app.state.metrics = mock_metrics

    response = await client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["power"] == 100
    assert data["speed"] == 5.5
    assert data["heart_rate"] == 140
    assert data["is_running"] is True
    mock_metrics.get_metrics.assert_called_once()


# -------------------------
# Test: Stream /metrics/stream and print to console
# -------------------------
@patch("app.api.Metrics")
@pytest.mark.asyncio
async def test_metrics_stream_console(mock_metrics_class, client):
    mock_metrics = MagicMock()

    # Thread-safe side effect
    mock_metrics.get_metrics.side_effect = lambda: MetricsModel(
        power=100,
        ma_power=95,
        speed=5.5,
        ma_speed=5.2,
        cadence=80,
        ma_cadence=78,
        distance=1200,
        ma_distance=1180,
        heart_rate=140,
        ma_heart_rate=138,
        heart_rate_percent=75,
        ma_heart_rate_percent=74,
        zone_name="MODERATE",
        ma_zone_name="MODERATE",
        zone_description="Moderate intensity",
        ma_zone_description="Moderate intensity",
        is_running=True,
        last_sensor_update=None,
        last_sensor_name=None,
    )

    mock_metrics_class.return_value = mock_metrics
    app.state.metrics = mock_metrics

    shutdown_event.clear()
    events = []
    timeout = 10  # seconds

    async def read_stream():
        async with client.stream("GET", "/metrics/stream") as response:
            print("fffo")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    payload = line[len("data: ") :].strip()
                    events.append(payload)
                    print("SSE event:", payload)

    try:
        await asyncio.wait_for(read_stream(), timeout=timeout)
    except asyncio.TimeoutError:
        shutdown_event.set()

    print(f"Collected {len(events)} SSE events")
    assert len(events) > 0
    for e in events:
        data = json.loads(e)
        assert "power" in data
