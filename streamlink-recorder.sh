#!/bin/sh

# Records the stream while it is live and looks again a minute after it ends or is offline, with its state on MQTT
# (streamlink_recorder). SIGTERM stops streamlink, which closes its file.
exec python -m streamlink_recorder
