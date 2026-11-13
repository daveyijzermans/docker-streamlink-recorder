# docker-streamlink-recorder

Records a livestream with [streamlink](https://github.com/streamlink/streamlink) and publishes the recorder's state on
MQTT.

## Description

The image is the official [Python image](https://hub.docker.com/_/python) (*slim-trixie*) with streamlink and the
recorder (`streamlink_recorder`), an MQTT bridge on [mqtt-bridge-core](https://github.com/daveyijzermans/mqtt-bridge-core)
(a submodule). The recorder runs streamlink while the stream is live and tries again a minute after it ends or finds
the stream offline.

## Usage

```bash
docker run -v /path/to/vod/folder/:/home/download \
  -e streamLink='twitch.tv/twitch' -e streamQuality='best' -e streamOptions='--twitch-disable-reruns' \
  -e MQTT_HOST='broker' -e MQTT_USERNAME='streamlink-recorder' -e MQTT_PASSWORD='...' \
  -e uid='1001' -e gid='1001' streamlink-recorder
```

Build it with the submodule checked out (`git clone --recurse-submodules`).

## Settings

`streamLink` - the url of the stream.

`streamQuality` - quality options (best, high, medium, low).

`streamName` - the channel's name on MQTT (default the link's last part, `twitch` above).

`streamOptions` - streamlink flags, separated by spaces (see [Plugins](https://streamlink.github.io/plugins.html)).

`MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD` - the broker and the recorder's login.

`MQTT_PREFIX` - the recorder's tree (default `streamlink-recorder`). Two recorders on one broker take a prefix each,
as the bridge's own availability and health sit under it.

`uid`, `gid` - the user and group the recorder runs and writes as (default 9001).

`/home/download` - where the recordings go, named `{time} - {title}.mkv`.

## MQTT

`<prefix>/<channel>/state`, retained:

- `state`: `recording` while a file is written, `waiting` between tries, `stopped` after a stop.
- `file`, `started`, `size`: the file being written (its name), when it began and its size in bytes, read every 30 s;
  null while not recording.
- `last_recording`: `{file, started, ended, size}` of the last finished file.

`<prefix>/<channel>/set` takes `start` or `stop` (or `ON` and `OFF`). Stop ends streamlink, which closes its file, and
the recorder holds until a start, across a restart too. Start tries at once.

`<prefix>/bridge/availability` (the channel's availability too) and `<prefix>/bridge/health` are the bridge's own; the container's healthcheck reads
`/tmp/streamlink-recorder.alive`.
