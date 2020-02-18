# Got this from https://hub.docker.com/r/rsrchboy/radvd/dockerfile
FROM alpine:3

RUN apk update && \
    apk add radvd && \
    rm -r /var/cache/

ENTRYPOINT [ "radvd", "--nodaemon", "-p", "/radvd.pid" ]
