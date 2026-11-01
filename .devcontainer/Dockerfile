FROM python:3.13-trixie

RUN apt-get update \
    && apt-get install --no-install-recommends -y git postgresql-client bubblewrap \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN curl -fsSL https://chatgpt.com/codex/install.sh | sh