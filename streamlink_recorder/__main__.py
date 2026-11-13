"""Run the recorder.

streamLink, streamQuality and streamOptions are streamlink's URL, quality and flags; streamName names the channel on
MQTT (default the link's last part). MQTT_HOST, MQTT_USERNAME and MQTT_PASSWORD are the broker and the recorder's
login; MQTT_PREFIX its tree (default streamlink-recorder). DOWNLOAD_DIR is where the files go (default
/home/download).
"""

from __future__ import annotations

import os
import shlex

from mqtt_bridge_core import Bridge, MqttSettings, run as run_service, slugify

from . import __version__
from .recorder import Recorder

NAME = "streamlink-recorder"


def channel_of(link: str, name: str = "") -> str:
    return slugify(name or link.rstrip("/").rsplit("/", 1)[-1])


def streamlink_argv(environ: "os._Environ[str] | dict[str, str]") -> list[str]:
    folder = environ.get("DOWNLOAD_DIR", "/home/download")
    return ["streamlink", *shlex.split(environ.get("streamOptions", "")), environ["streamLink"],
            environ.get("streamQuality", "best"), "-o", f"{folder}/{{time}} - {{title}}.mkv"]


async def main() -> None:
    settings = MqttSettings.from_env(prefix=NAME)
    channel = channel_of(os.environ["streamLink"], os.environ.get("streamName", ""))
    bridge = Bridge(NAME, __version__, settings, client_id=f"{NAME}-{channel}", health_file=f"/tmp/{NAME}.alive")
    recorder = Recorder(bridge, settings.prefix, channel, streamlink_argv(os.environ))
    bridge.alive = recorder.alive
    recorder.task = bridge.spawn(recorder.run())
    await bridge.run()


def run() -> None:
    run_service(main)


if __name__ == "__main__":
    run()
