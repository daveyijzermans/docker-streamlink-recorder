"""streamlink as the recorder sees it: `offline` ends at once as streamlink does on an offline channel; `live <path>
<seconds>` writes the file for that long, logging as streamlink 8 does, and closes it on SIGTERM."""

import signal
import sys
import time

mode = sys.argv[1]
print("[cli][info] Found matching plugin twitch for URL twitch.tv/lekkerspelen", flush=True)
if mode == "offline":
    print("error: No playable streams found on this URL: twitch.tv/lekkerspelen", flush=True)
    sys.exit(1)

path, seconds = sys.argv[2], float(sys.argv[3])
stop = False


def term(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, term)
print("[cli][info] Available streams: audio_only, 160p (worst), 360p, 480p, 720p60, 1080p60 (best)", flush=True)
print("[cli][info] Opening stream: 1080p60 (hls)", flush=True)
print(f"[cli][info] Writing output to\n{path}", flush=True)
end = time.monotonic() + seconds
with open(path, "wb") as f:
    while not stop and time.monotonic() < end:
        f.write(b"x" * 1000)
        f.flush()
        time.sleep(0.05)
print("[cli][info] Stream ended", flush=True)
print("[cli][info] Closing currently open stream...", flush=True)
