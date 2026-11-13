"""The recorder against a fake streamlink on a fake bridge: waiting while offline, a recording's file, start, size and
end, a stop that closes the file and holds until a start, a stop read back from the retained state, and the
streamlink command line from the environment."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
from mqtt_bridge_core.testing import FakeBridge

from streamlink_recorder.__main__ import channel_of, streamlink_argv
from streamlink_recorder.recorder import Recorder

FAKE = os.path.join(os.path.dirname(__file__), "fake_streamlink.py")
STATE, SET = "streamlink-recorder/lekkerspelen/state", "streamlink-recorder/lekkerspelen/set"


def recorder(bridge, *args, **kw):
    return Recorder(bridge, "streamlink-recorder", "lekkerspelen", [sys.executable, FAKE, *args],
                    check_every=kw.pop("check_every", 0.2), size_every=0.1, clock=lambda: "2026-11-13T20:00:00+01:00",
                    **kw)


def states(bridge):
    return [s["state"] for s in bridge.states["lekkerspelen"]]


async def until(check, seconds=5.0):
    for _ in range(int(seconds / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("never held")


def test_offline_waits_and_tries_again():
    async def go():
        bridge = FakeBridge(prefix="streamlink-recorder")
        rec = recorder(bridge, "offline")
        rec.task = asyncio.create_task(rec.run())
        await asyncio.sleep(0.6)
        rec.task.cancel()
        doc = bridge.states["lekkerspelen"][-1]
        assert doc == {"state": "waiting", "file": None, "started": None, "size": None, "last_recording": None}
        assert set(states(bridge)) == {"waiting"}
    asyncio.run(go())


def test_recording_follows_the_stream(tmp_path):
    async def go():
        path = tmp_path / "2026-11-13_20-00-00 - Live.mkv"
        bridge = FakeBridge(prefix="streamlink-recorder")
        rec = recorder(bridge, "live", str(path), "0.5", check_every=30)
        rec.task = asyncio.create_task(rec.run())
        await until(lambda: rec.state == "recording")
        doc = bridge.states["lekkerspelen"][-1]
        assert doc["file"] == path.name and doc["started"] == "2026-11-13T20:00:00+01:00"
        await until(lambda: (bridge.states["lekkerspelen"][-1]["size"] or 0) > 0)
        await until(lambda: rec.last is not None)
        rec.task.cancel()
        doc = bridge.states["lekkerspelen"][-1]
        assert doc["state"] == "waiting" and doc["file"] is None and doc["size"] is None
        assert doc["last_recording"] == {"file": path.name, "started": "2026-11-13T20:00:00+01:00",
                                         "ended": "2026-11-13T20:00:00+01:00", "size": path.stat().st_size}
        assert states(bridge)[:2] == ["waiting", "recording"]
    asyncio.run(go())


def test_stop_closes_the_file_and_holds_until_start(tmp_path):
    async def go():
        path = tmp_path / "rec.mkv"
        bridge = FakeBridge(prefix="streamlink-recorder")
        rec = recorder(bridge, "live", str(path), "60", check_every=0.1)
        rec.task = asyncio.create_task(rec.run())
        await until(lambda: rec.state == "recording")
        await bridge.deliver(SET, "stop")
        assert rec.proc is None or rec.proc.returncode is not None  # streamlink has ended when stop returns
        await until(lambda: bridge.states["lekkerspelen"][-1]["state"] == "stopped")
        doc = bridge.states["lekkerspelen"][-1]
        assert doc["last_recording"]["file"] == "rec.mkv"
        assert doc["last_recording"]["size"] == path.stat().st_size
        size = path.stat().st_size
        await asyncio.sleep(0.4)  # no try while stopped
        assert path.stat().st_size == size and rec.state == "stopped"
        await bridge.deliver(SET, "start")
        await until(lambda: rec.state == "recording")
        await bridge.deliver(SET, "OFF")
        await until(lambda: rec.state == "stopped")
        rec.task.cancel()
    asyncio.run(go())


def test_a_retained_stop_holds_after_a_restart():
    async def go():
        held = {"state": "stopped", "file": None, "started": None, "size": None,
                "last_recording": {"file": "a.mkv", "started": "s", "ended": "e", "size": 5}}
        bridge = FakeBridge(prefix="streamlink-recorder", retained={STATE: json.dumps(held)})
        rec = recorder(bridge, "offline")
        rec.task = asyncio.create_task(rec.run())
        await asyncio.sleep(0.3)
        assert states(bridge) == ["stopped"]
        assert bridge.states["lekkerspelen"][-1]["last_recording"] == held["last_recording"]
        await bridge.deliver(SET, "start")
        await until(lambda: "waiting" in states(bridge))
        rec.task.cancel()
    asyncio.run(go())


def test_an_unknown_command_does_nothing():
    async def go():
        bridge = FakeBridge(prefix="streamlink-recorder")
        rec = recorder(bridge, "offline", check_every=30)
        rec.task = asyncio.create_task(rec.run())
        await asyncio.sleep(0.2)
        await bridge.deliver(SET, "pause")
        assert not rec.stopped
        rec.task.cancel()
    asyncio.run(go())


def test_a_retained_command_is_not_acted_on():
    async def go():
        bridge = FakeBridge(prefix="streamlink-recorder")
        rec = recorder(bridge, "offline", check_every=30)
        rec.task = asyncio.create_task(rec.run())
        await asyncio.sleep(0.2)
        await bridge.deliver(SET, "stop", retain=True)
        assert not rec.stopped
        rec.task.cancel()
    asyncio.run(go())


@pytest.mark.parametrize("link,name,channel", [("twitch.tv/lekkerspelen", "", "lekkerspelen"),
                                               ("https://www.twitch.tv/LekkerSpelen/", "", "lekkerspelen"),
                                               ("twitch.tv/x", "Mijn Kanaal", "mijn_kanaal")])
def test_channel_names(link, name, channel):
    assert channel_of(link, name) == channel


def test_streamlink_command_line():
    env = {"streamLink": "twitch.tv/lekkerspelen", "streamQuality": "best",
           "streamOptions": "--twitch-disable-reruns --retry-open 3"}
    assert streamlink_argv(env) == ["streamlink", "--twitch-disable-reruns", "--retry-open", "3",
                                    "twitch.tv/lekkerspelen", "best", "-o", "/home/download/{time} - {title}.mkv"]
