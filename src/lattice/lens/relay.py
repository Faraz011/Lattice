"""The pairing relay for the two-device demo, and the web server for its pages.

Devices join a room by code over a WebSocket (`/ws/{room}`). Every message a device sends is
passed to the other devices in the room; the relay reads nothing in it beyond its `type`. The
latest message of each type is kept, so a device that joins late (or reconnects) sees the
current scene and the current switched-off neurons at once.

    uv run python -m lattice.lens.relay --port 8090                 # development, with Vite
    uv run python -m lattice.lens.relay --static lens/dist          # production: one service

Rooms live in memory: a restart empties them, and the devices resend their state on reconnect.
"""

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOM = re.compile(r"^[A-Za-z0-9-]{3,32}$")
MAX_MESSAGE = 64 * 1024
MAX_ROOMS = 200
MAX_PEERS = 8


class Rooms:
    def __init__(self) -> None:
        self.peers: dict[str, set[WebSocket]] = defaultdict(set)
        self.latest: dict[str, dict[str, str]] = defaultdict(dict)
        self.lock = asyncio.Lock()

    async def join(self, room: str, ws: WebSocket) -> bool:
        async with self.lock:
            if room not in self.peers and len(self.peers) >= MAX_ROOMS:
                return False
            if len(self.peers[room]) >= MAX_PEERS:
                return False
            self.peers[room].add(ws)
            return True

    async def leave(self, room: str, ws: WebSocket) -> None:
        async with self.lock:
            self.peers[room].discard(ws)
            if not self.peers[room]:
                del self.peers[room]
                self.latest.pop(room, None)

    async def relay(self, room: str, sender: WebSocket, text: str, kind: str) -> None:
        async with self.lock:
            self.latest[room][kind] = text
            others = [p for p in self.peers.get(room, ()) if p is not sender]
        for peer in others:
            with contextlib.suppress(RuntimeError):  # closed between the snapshot and the send
                await peer.send_text(text)


def create_app(static: Path | None = None) -> FastAPI:
    app = FastAPI(title="Lattice Lens relay", docs_url=None, redoc_url=None)
    rooms = Rooms()

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "rooms": len(rooms.peers)})

    @app.websocket("/ws/{room}")
    async def socket(ws: WebSocket, room: str) -> None:
        if not ROOM.match(room):
            await ws.close(code=4400)
            return
        await ws.accept()
        if not await rooms.join(room, ws):
            await ws.close(code=4429)
            return
        try:
            for text in list(rooms.latest.get(room, {}).values()):
                await ws.send_text(text)
            while True:
                text = await ws.receive_text()
                if len(text) > MAX_MESSAGE:
                    continue
                try:
                    kind = str(json.loads(text).get("type", ""))[:32]
                except (ValueError, AttributeError):
                    continue
                if kind:
                    await rooms.relay(room, ws, text, kind)
        except WebSocketDisconnect:
            pass
        finally:
            await rooms.leave(room, ws)

    if static and static.is_dir():
        index = static / "index.html"
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}")
        async def files(path: str) -> FileResponse:
            target = (static / path).resolve()
            if path and target.is_file() and static.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(index)  # the app routes by hash; every other path is the app

    return app


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="lattice.lens.relay", description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8090")))
    parser.add_argument("--static", type=Path, default=None,
                        help="serve the built app from this folder (lens/dist)")
    args = parser.parse_args(argv)
    uvicorn.run(create_app(args.static), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
