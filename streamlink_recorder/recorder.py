"""One channel's recorder: streamlink runs while the stream is live and is tried again CHECK_EVERY after it ends or
finds the stream offline.

The state document on `<prefix>/<channel>/state`, retained:

- `state`: `recording` while streamlink writes a file, `waiting` between tries, `stopped` after a stop command.
- `file`, `started`, `size`: the file being written (its name in the download folder), when it began and its bytes,
  read every SIZE_EVERY; null while not recording.
- `last_recording`: `{file, started, ended, size}` of the last finished file, null before the first.

Its availability is the bridge's, `<prefix>/bridge/availability`.

`<prefix>/<channel>/set` takes `start` or `stop` (or ON and OFF). Stop ends streamlink, which closes its file, and no
try follows until a start, a restart of the container included: the stop is read back from the retained state. Start
tries at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

from mqtt_bridge_core import CommandError, Device, Entity, command, read_on_off

_LOGGER = logging.getLogger(__name__)
CHECK_EVERY = 60.0
SIZE_EVERY = 30.0
STOP_GRACE = 20.0
WRITING = "Writing output to"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Recorder:
    def __init__(self, bridge: Any, prefix: str, channel: str, argv: Sequence[str], *,
                 check_every: float = CHECK_EVERY, size_every: float = SIZE_EVERY,
                 clock: Callable[[], str] = now) -> None:
        """argv: the streamlink command, its output path included."""
        self.bridge, self.argv, self.clock = bridge, list(argv), clock
        self.check_every, self.size_every = check_every, size_every
        base = f"{prefix}/{channel}"
        self.device = Device(channel, state_topic=f"{base}/state",
                             availability_topic=f"{prefix}/bridge/availability",
                             entities=[Entity("recording", command_topic=f"{base}/set",
                                              on_command=command(self.on_command, f"{base}/set"))])
        self.state = "waiting"
        self.path: Optional[str] = None
        self.started: Optional[str] = None
        self.size: Optional[int] = None
        self.last: Optional[dict[str, Any]] = None
        self.stopped = False
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.wake = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

    def alive(self) -> bool:
        return self.task is not None and not self.task.done()

    def document(self) -> dict[str, Any]:
        return {"state": self.state, "file": os.path.basename(self.path) if self.path else None,
                "started": self.started, "size": self.size, "last_recording": self.last}

    async def publish(self) -> None:
        self.device.state, self.device.available = self.document(), True
        await self.bridge.publish_device(self.device)

    async def on_command(self, payload: str) -> None:
        word = payload.strip().lower()
        on = read_on_off(payload)
        if word == "start" or on is True:
            await self.start()
        elif word == "stop" or on is False:
            await self.stop()
        else:
            raise CommandError(f"neither start nor stop: {payload[:80]!r}")

    async def start(self) -> None:
        if self.stopped:
            _LOGGER.info("%s: started", self.device.name)
        self.stopped = False
        self.wake.set()

    async def stop(self) -> None:
        """Returns once streamlink has ended; the loop publishes the stop, with the finished file."""
        if not self.stopped:
            _LOGGER.info("%s: stopped", self.device.name)
        self.stopped = True
        self.wake.set()
        await self.end_streamlink()

    async def end_streamlink(self) -> None:
        """SIGTERM to streamlink, which closes its file; killed after STOP_GRACE."""
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), STOP_GRACE)
        except TimeoutError:
            _LOGGER.warning("%s: streamlink did not end on SIGTERM, killed", self.device.name)
            proc.kill()
            await proc.wait()

    async def resume(self) -> None:
        """A stop and the last recording, as the retained state holds them."""
        held = await self.bridge.retained(self.device.state_topic)
        try:
            doc = json.loads(held) if held else None
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            self.stopped = doc.get("state") == "stopped"
            if isinstance(doc.get("last_recording"), dict):
                self.last = doc["last_recording"]
            # a file the previous run was writing when it ended
            if doc.get("state") == "recording" and doc.get("file"):
                self.last = {"file": doc["file"], "started": doc.get("started"), "ended": None,
                             "size": doc.get("size")}
        if self.stopped:
            self.state = "stopped"
            _LOGGER.info("%s: stays stopped until a start", self.device.name)

    async def run(self) -> None:
        await self.bridge.wait_connected()
        await self.resume()
        while True:
            if self.stopped:
                self.state = "stopped"
                await self.publish()
                while self.stopped:
                    self.wake.clear()
                    if self.stopped:
                        await self.wake.wait()
                continue
            self.state = "waiting"
            await self.publish()
            self.wake.clear()
            if self.stopped:
                continue
            await self.record()
            if self.stopped:
                continue
            self.state = "waiting"
            await self.publish()
            try:
                await asyncio.wait_for(self.wake.wait(), self.check_every)
            except TimeoutError:
                pass

    async def record(self) -> None:
        """One run of streamlink: a recording from the moment it writes its file until it ends."""
        self.proc = await asyncio.create_subprocess_exec(*self.argv, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.STDOUT)
        sizes = asyncio.create_task(self.sizes())
        try:
            if self.stopped:  # a stop while streamlink was starting
                await self.end_streamlink()
            path_next = False
            assert self.proc.stdout is not None
            async for raw in self.proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                print(line, flush=True)
                if path_next:
                    path_next = False
                    await self.begin(line.strip())
                elif line.endswith(WRITING):
                    path_next = True
            await self.proc.wait()
        finally:
            sizes.cancel()
            await asyncio.shield(self.end_streamlink())
            self.proc = None
            if self.path:
                await asyncio.shield(self.finish())

    async def begin(self, path: str) -> None:
        self.path, self.started, self.size = path, self.clock(), self.file_size(path)
        self.state = "recording"
        _LOGGER.info("%s: recording %s", self.device.name, path)
        await self.publish()

    async def finish(self) -> None:
        self.last = {"file": os.path.basename(self.path or ""), "started": self.started, "ended": self.clock(),
                     "size": self.file_size(self.path)}
        _LOGGER.info("%s: recorded %s, %s bytes", self.device.name, self.path, self.last["size"])
        self.path = self.started = self.size = None
        self.state = "stopped" if self.stopped else "waiting"
        await self.publish()

    @staticmethod
    def file_size(path: Optional[str]) -> Optional[int]:
        try:
            return os.path.getsize(path) if path else None
        except OSError:
            return None

    async def sizes(self) -> None:
        while True:
            await asyncio.sleep(self.size_every)
            if self.path:
                self.size = self.file_size(self.path)
                await self.publish()
