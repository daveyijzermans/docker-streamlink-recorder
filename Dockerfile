FROM python:3.14.10-slim-trixie
LABEL maintainer="lauwarm@mailbox.org"

ARG STREAMLINK_VERSION=8.6.3

RUN apt-get update && \
	apt-get install -y --no-install-recommends gosu procps && \
	rm -rf /var/lib/apt/lists/* && \
	pip install --no-cache-dir streamlink==${STREAMLINK_VERSION} && \
	mkdir -p /home/download /home/script /home/plugins

COPY ./streamlink-recorder.sh ./entrypoint.sh /home/script/

RUN chmod +x /home/script/entrypoint.sh /home/script/streamlink-recorder.sh

ENTRYPOINT [ "/home/script/entrypoint.sh" ]

# The script reads streamOptions, streamLink and streamQuality from the environment.
CMD [ "/home/script/streamlink-recorder.sh" ]
