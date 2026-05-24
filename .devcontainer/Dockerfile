FROM mcr.microsoft.com/devcontainers/python:3.11

RUN sudo apt update \
    && sudo apt install -y --no-install-recommends \
        iputils-ping \
        iw \
    && rm -rf /var/lib/apt/lists/*

COPY vcgencmd /usr/local/bin/vcgencmd
RUN chmod +x /usr/local/bin/vcgencmd

WORKDIR /workspace