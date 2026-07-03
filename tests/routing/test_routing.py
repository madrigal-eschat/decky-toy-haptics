import pytest
from unittest.mock import Mock, AsyncMock

from main import HapticsBridge

pytestmark = pytest.mark.asyncio

@pytest_asyncio.fixture
async def mock_client():
    """Create mock buttplug client with 3 devices."""
    client = Mock()
    device1 = Mock()
    device1.index = 1
    device1.name = "Toy1"
    device1.actuators = [Mock(index=0), Mock(index=1)]
    device2 = Mock()
    device2.index = 2
    device2.name = "Toy2"
    device2.actuators = [Mock(index=2)]
    client.devices = {1: device1, 2: device2}
    return client

pytest_asyncio.fixture = pytest_asyncio.fixture

@pytest_asyncio.fixture
async def bridge(mock_client):
    """Create HapticsBridge instance."""
    bridge = HapticsBridge()
    bridge._client = mock_client
    bridge._scale = 1.0
    bridge._device_map = {}
    bridge._throttle = 0.10
    return bridge

@pytest_asyncio.fixture
async def bridge_with_map(mock_client):
    """Create HapticsBridge with device map."""
    bridge = HapticsBridge()
    bridge._client = mock_client
    bridge._scale = 1.0
    bridge._device_map = {
        101: "1",
        102: "2",
        103: "0",
    }
    bridge._throttle = 0.10
    return bridge

class TestDeviceMap:
    """Test HapticsBridge device mapping routing logic."""

    def test_undefined_effect_uses_round_robin(self, bridge):
        """Effect with no mapping uses round-robin."""
        result = bridge._get_toy_index_for_effect(999)
        assert result == 1

    def test_mapped_effect_returns_correct_index(self, bridge_with_map):
        """Effect with mapping returns mapped index."""
        assert bridge_with_map._get_toy_index_for_effect(101) == 1
        assert bridge_with_map._get_toy_index_for_effect(102) == 2
        assert bridge_with_map._get_toy_index_for_effect(103) == 0

    def test_invalid_mapped_string_fallbacks(self, bridge_with_map):
        """Invalid mapping string falls back to round-robin."""
        bridge_with_map._device_map[-1] = "invalid"
        result = bridge_with_map._get_toy_index_for_effect(-1)
        assert isinstance(result, int)
        assert result == 1

    def test_empty_device_map_uses_round_robin(self, bridge):
        """Empty device map always uses round-robin."""
        result = bridge._next_available_toy_index()
        assert isinstance(result, int)

async def test_effect_dispatch_uses_routed_toy(bridge_with_map):
    """_emit_haptic dispatches to routed toy index."""
    # Mock client.send
    bridge_with_map._client.send = AsyncMock()

    await bridge_with_map._emit_haptic(101, [
        {"dt_ms": 0, "intensity": 0.8, "waveform": 0x50},
        {"dt_ms": 50, "intensity": 0.5, "waveform": 0x50},
    ])

    # First call should be to Toy1 actuator 1
    bridge_with_map._client.send.assert_called_once()
    call_args = bridge_with_map._client.send.call_args
    assert call_args[1]["DeviceIndex"] == 1

async def test_second_effect_uses_different_toy(bridge_with_map):
    """Second effect_id uses different toy from map."""
    bridge_with_map._client.send = AsyncMock()

    await bridge_with_map._emit_haptic(101, [
        {"dt_ms": 0, "intensity": 0.5, "waveform": 0x50},
    ])
    bridge_with_map._client.send.assert_called_once()
    assert bridge_with_map._client.send.call_args[1]["DeviceIndex"] == 1

    bridge_with_map._client.send.reset_mock()

    await bridge_with_map._emit_haptic(102, [
        {"dt_ms": 0, "intensity": 0.6, "waveform": 0x50},
    ])
    bridge_with_map._client.send.assert_called_once()
    assert bridge_with_map._client.send.call_args[1]["DeviceIndex"] == 2
