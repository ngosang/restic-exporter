FROM golang:1.24-alpine3.23 AS builder

ENV RESTIC_VERSION=0.18.1
ENV CGO_ENABLED=0

RUN cd /tmp \
    # download restic source code
    && wget https://github.com/restic/restic/archive/refs/tags/v${RESTIC_VERSION}.tar.gz -O restic.tar.gz \
    && tar xvf restic.tar.gz \
    && cd restic-* \
    # build the executable
    # flag -ldflags "-s -w" produces a smaller executable
    && go build -ldflags "-s -w" -v -o /tmp/restic ./cmd/restic

FROM python:3.14-alpine3.23

# libc6-compat => https://github.com/ngosang/restic-exporter/issues/36
RUN apk add --no-cache --update openssh tzdata libc6-compat

COPY --from=builder /tmp/restic /usr/bin

RUN pip install prometheus-client==0.23.1 \
    # remove temporary files
    && rm -rf /root/.cache

COPY exporter/exporter.py pyproject.toml /app/
EXPOSE 8001

CMD ["/usr/local/bin/python", "-u", "/app/exporter.py"]

# Help
#
# Local build
# docker build -t restic-exporter:custom --progress=plain .
#
# Multi-arch build
# -> Register interpreters for common architectures
# docker run --rm --privileged tonistiigi/binfmt:latest --install all
# -> Create a new buildx builder
# docker buildx create --use
# -> Build for multiple architectures (run 2 commands separately to avoid filling the disk)
# docker buildx build -t restic-exporter:custom --platform linux/386,linux/amd64,linux/arm/v6,linux/arm/v7 --progress=plain .
# docker buildx build -t restic-exporter:custom --platform linux/arm64,linux/ppc64le,linux/riscv64,linux/s390x --progress=plain .
#
# add --push to publish in DockerHub
