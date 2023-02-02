FROM golang:1.19-alpine3.17 AS builder

ENV RESTIC_VERSION 0.15.1
ENV CGO_ENABLED 0

RUN cd /tmp \
    # download restic source code
    && wget https://github.com/restic/restic/archive/refs/tags/v${RESTIC_VERSION}.tar.gz -O restic.tar.gz \
    && tar xvf restic.tar.gz \
    && cd restic-* \
    # build the executable
    # flag -ldflags "-s -w" produces a smaller executable
    && go build -ldflags "-s -w" -v -o /tmp/restic ./cmd/restic

FROM python:3.11-alpine3.17

RUN apk add --no-cache --update tzdata

COPY --from=builder /tmp/restic /usr/bin
COPY entrypoint.sh requirements.txt /

RUN pip install -r /requirements.txt \
    # remove temporary files
    && rm -rf /root/.cache

COPY ./restic-exporter.py /restic-exporter.py

EXPOSE 8001

CMD [ "/entrypoint.sh" ]

# Help
#
# Local build
# docker build -t restic-exporter:custom .
#
# Multi-arch build
# docker buildx create --use
# docker buildx build -t restic-exporter:custom --platform linux/386,linux/amd64,linux/arm/v6,linux/arm/v7,linux/arm64/v8,linux/ppc64le,linux/s390x .
#
# add --push to publish in DockerHub
