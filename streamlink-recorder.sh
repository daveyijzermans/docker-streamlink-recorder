#!/bin/sh

# For more information visit: https://github.com/downthecrop/TwitchVOD

# Records the stream while it is live and looks again a minute after it ends or is offline.
# SIGTERM stops streamlink, which closes its file, and then the loop.
trap 'kill -TERM "$pid" 2>/dev/null; wait "$pid"; exit 0' TERM INT

while true; do
	streamlink $streamOptions "$streamLink" "$streamQuality" -o "/home/download/{time} - {title}.mkv" &
	pid=$!
	wait "$pid"
	sleep 60 &
	pid=$!
	wait "$pid"
done
