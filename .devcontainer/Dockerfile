FROM mcr.microsoft.com/devcontainers/python:3.11

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY vcgencmd /usr/local/bin/vcgencmd
COPY iw /usr/local/bin/iw
RUN chmod +x \
    /usr/local/bin/vcgencmd \
    /usr/local/bin/iw

RUN pip install --no-cache-dir \
    pytest \
    ruff

WORKDIR /workspace