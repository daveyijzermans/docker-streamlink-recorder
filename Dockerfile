FROM python:3.14.10-slim-trixie
LABEL maintainer="lauwarm@mailbox.org"

ARG STREAMLINK_VERSION=8.6.3

RUN apt-get update && \
	apt-get install -y --no-install-recommends gosu procps && \
	rm -rf /var/lib/apt/lists/* && \
	pip install --no-cache-dir --root-user-action=ignore streamlink==${STREAMLINK_VERSION} aiomqtt==2.5.1 && \
	mkdir -p /home/download /home/script /home/plugins

# mqtt-bridge-core is a submodule
COPY mqtt-bridge-core /tmp/mqtt-bridge-core
RUN pip install --no-cache-dir --root-user-action=ignore /tmp/mqtt-bridge-core && rm -rf /tmp/mqtt-bridge-core

COPY pyproject.toml README.md /tmp/recorder/
COPY streamlink_recorder /tmp/recorder/streamlink_recorder
RUN pip install --no-cache-dir --root-user-action=ignore --no-deps /tmp/recorder && rm -rf /tmp/recorder

COPY ./streamlink-recorder.sh ./entrypoint.sh /home/script/

RUN chmod +x /home/script/entrypoint.sh /home/script/streamlink-recorder.sh

HEALTHCHECK --interval=60s --timeout=5s --start-period=60s \
	CMD python -c "import os,sys,time; sys.exit(time.time()-os.path.getmtime('/tmp/streamlink-recorder.alive') > 180)"

ENTRYPOINT [ "/home/script/entrypoint.sh" ]

# The recorder reads streamOptions, streamLink, streamQuality, streamName and the MQTT_* login from the environment.
CMD [ "/home/script/streamlink-recorder.sh" ]
