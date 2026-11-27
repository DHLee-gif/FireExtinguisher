"""Stand-in web app for testing the stream without the real one. Not started by main.py.

  /ingest  the car (stream/run.py) connects here and pushes JPEG frames
  /view    browsers connect here and get the newest frame
  /        viewer page: open http://<this computer>:8090/ in a browser

usage: dev_server.py [--host 0.0.0.0] [--port 8090]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from http import HTTPStatus

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>소방 RC카 화면 (시험용)</title>
<style>
 body{margin:0;background:#111;color:#eee;font-family:sans-serif;text-align:center}
 img{max-width:100%;max-height:85vh;background:#222;margin-top:8px}
 #info{padding:8px;font-size:15px}
 .bad{color:#f66}.ok{color:#6f6}
</style></head><body>
<div id="info">연결 중...</div>
<img id="video" alt="">
<script>
const info = document.getElementById("info"), video = document.getElementById("video");
let state = {server: "연결 중", car: "?", camera: "?"}, frames = 0, fps = 0, lastUrl = null;
function show() {
  const cls = state.server === "연결됨" && state.car === "연결됨" && state.camera === "ok" ? "ok" : "bad";
  info.innerHTML = `<span class="${cls}">서버: ${state.server} · 차: ${state.car} · 카메라: ${state.camera}</span> · ${fps} fps`;
}
setInterval(() => { fps = frames; frames = 0; show(); }, 1000);
function open() {
  const ws = new WebSocket(`ws://${location.host}/view`);
  ws.binaryType = "blob";
  ws.onopen = () => { state.server = "연결됨"; show(); };
  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);
      if (msg.type === "car") state.car = msg.connected ? "연결됨" : "끊김";
      if (msg.type === "status") state.camera = msg.camera;
      show(); return;
    }
    const url = URL.createObjectURL(event.data);
    video.onload = () => { if (lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url; };
    video.src = url; frames++;
  };
  ws.onclose = () => { state.server = "끊김"; show(); setTimeout(open, 1000); };
}
open();
</script></body></html>
"""


class Hub:
    """Keeps only the newest frame. Each viewer gets the newest one when it is ready."""

    def __init__(self):
        self.frame, self.version = None, 0
        self.cars, self.car_connected, self.camera = 0, False, "?"
        self.changed = asyncio.Condition()

    async def update(self, **values):
        async with self.changed:
            for key, value in values.items():
                setattr(self, key, value)
            if "frame" in values:
                self.version += 1
            self.changed.notify_all()


async def ingest(hub: Hub, websocket):
    # A car that reconnects may arrive before its dead old connection times out, so count them.
    print(f"car connected from {websocket.remote_address}", file=sys.stderr)
    await hub.update(cars=hub.cars + 1, car_connected=True)
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                await hub.update(frame=message)
                continue
            data = json.loads(message)
            if data.get("type") == "hello":
                print(f"hello: {data}", file=sys.stderr)
            elif data.get("type") == "status":
                await hub.update(camera=data.get("camera", "?"))
    except (ConnectionClosed, ValueError) as error:
        print(f"car connection ended: {type(error).__name__}: {error}", file=sys.stderr)
    finally:
        cars = hub.cars - 1
        await hub.update(cars=cars, car_connected=cars > 0, **({} if cars else {"camera": "?"}))
        print("car disconnected", file=sys.stderr)


async def view(hub: Hub, websocket):
    sent_version, sent_state = 0, None
    try:
        while True:
            async with hub.changed:
                try:
                    await asyncio.wait_for(hub.changed.wait_for(
                        lambda: hub.version != sent_version
                        or (hub.car_connected, hub.camera) != sent_state), 1.0)
                except TimeoutError:
                    if websocket.state is State.CLOSED:
                        return  # Tab closed while no car was sending.
                    continue
                frame, version, state = hub.frame, hub.version, (hub.car_connected, hub.camera)
            if state != sent_state:
                await websocket.send(json.dumps({"type": "car", "connected": state[0]}))
                await websocket.send(json.dumps({"type": "status", "camera": state[1]}))
                sent_state = state
            if version != sent_version and frame is not None:
                await websocket.send(frame)  # Slow viewer: frames that arrive meanwhile are skipped.
            sent_version = version
    except ConnectionClosed:
        pass  # The browser tab was closed.


def handle_http(connection, request):
    if request.path == "/":
        response = connection.respond(HTTPStatus.OK, PAGE)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response
    if request.path not in ("/ingest", "/view"):
        return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
    return None  # WebSocket upgrade continues.


async def serve_forever(host: str, port: int):
    hub = Hub()

    async def route(websocket):
        if websocket.request.path == "/ingest":
            await ingest(hub, websocket)
        else:
            await view(hub, websocket)

    async with serve(route, host, port, process_request=handle_http, max_size=4 * 1024 * 1024,
                     compression=None):
        print(f"viewer: http://{host}:{port}/   car pushes to ws://<this computer>:{port}/ingest",
              file=sys.stderr)
        await asyncio.get_running_loop().create_future()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    try:
        asyncio.run(serve_forever(args.host, args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
