import json
from dataclasses import dataclass, field
import websockets
import websockets.server


def _device_messages_schema() -> dict:
    return {
        "ScalarCmd": [
            {"StepCount": 20, "ActuatorType": "Vibrate", "FeatureDescriptor": ""}
        ]
    }


@dataclass
class FakeDevice:
    index: int
    name: str


class MockIntifaceServer:
    """Minimal Buttplug v3 WebSocket server for use in tests."""

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.received_commands: list[dict] = []
        self._fake_devices: list[FakeDevice] = []
        self._server: websockets.server.WebSocketServer | None = None

    def add_fake_device(self, index: int, name: str) -> None:
        self._fake_devices.append(FakeDevice(index=index, name=name))

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, websocket) -> None:
        async for raw in websocket:
            for msg in json.loads(raw):
                msg_type, payload = next(iter(msg.items()))
                await self._dispatch(websocket, msg_type, payload)

    async def _dispatch(self, websocket, msg_type: str, payload: dict) -> None:
        msg_id = payload.get("Id", 0)

        if msg_type == "RequestServerInfo":
            await websocket.send(json.dumps([{
                "ServerInfo": {
                    "Id": msg_id,
                    "MessageVersion": 3,
                    "MaxPingTime": 0,
                    "ServerName": "mock-intiface",
                }
            }]))

        elif msg_type == "RequestDeviceList":
            devices = [
                {
                    "DeviceIndex": d.index,
                    "DeviceName": d.name,
                    "DeviceDisplayName": d.name,
                    "DeviceMessageTimingGap": 0,
                    "DeviceMessages": _device_messages_schema(),
                }
                for d in self._fake_devices
            ]
            await websocket.send(json.dumps([
                {"DeviceList": {"Id": msg_id, "Devices": devices}}
            ]))

        elif msg_type == "StartScanning":
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))
            for d in self._fake_devices:
                await websocket.send(json.dumps([{
                    "DeviceAdded": {
                        "Id": 0,
                        "DeviceIndex": d.index,
                        "DeviceName": d.name,
                        "DeviceDisplayName": d.name,
                        "DeviceMessageTimingGap": 0,
                        "DeviceMessages": _device_messages_schema(),
                    }
                }]))
            await websocket.send(json.dumps([{"ScanningFinished": {"Id": 0}}]))

        elif msg_type == "StopScanning":
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))

        elif msg_type in ("ScalarCmd", "VibrateCmd", "StopAllDevices"):
            self.received_commands.append({msg_type: payload})
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))

        else:
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))
