"""End to end on this computer: car stream -> stand-in web app -> browser viewer."""

import asyncio
import json
import unittest
import urllib.request

from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve

import dev_server
from run import load_config, run, send_frames
from test_run import Camera, stop_after


class EndToEndTest(unittest.TestCase):
    def test_viewer_receives_live_frames_and_camera_state(self):
        async def scenario():
            hub = dev_server.Hub()

            async def route(websocket):
                if websocket.request.path == "/ingest":
                    await dev_server.ingest(hub, websocket)
                else:
                    await dev_server.view(hub, websocket)

            async with serve(route, "127.0.0.1", 0, process_request=dev_server.handle_http) as server:
                port = server.sockets[0].getsockname()[1]
                config = {**load_config(), "server_url": f"ws://127.0.0.1:{port}/ingest", "fps": 10}
                camera = Camera()
                car = asyncio.create_task(run(
                    config, stop_after(1.5), log=lambda _: None,
                    send=lambda socket, c, stop: send_frames(socket, c, stop, camera)))
                frames, texts = 0, []
                async with ws_connect(f"ws://127.0.0.1:{port}/view") as viewer:
                    try:
                        async with asyncio.timeout(1.2):
                            async for message in viewer:
                                if isinstance(message, bytes):
                                    frames += 1
                                else:
                                    texts.append(json.loads(message))
                    except TimeoutError:
                        pass
                page = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode())
                await car
                return frames, texts, page

        frames, texts, page = asyncio.run(scenario())
        self.assertGreaterEqual(frames, 5)
        self.assertIn({"type": "car", "connected": True}, texts)
        self.assertIn({"type": "status", "camera": "ok"}, texts)
        self.assertIn("<img", page)


if __name__ == "__main__":
    unittest.main()
