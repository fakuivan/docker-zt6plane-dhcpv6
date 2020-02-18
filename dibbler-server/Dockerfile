FROM ubuntu:18.04

RUN apt update && apt install dibbler-server -y

EXPOSE 547/TCP 547/UDP

WORKDIR  /etc/dibbler

ENTRYPOINT ["/usr/sbin/dibbler-server"]

