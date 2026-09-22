# jev-ra with a Chromium of its own, so nobody has to install one:
#   docker build -t jev-ra .
#   docker run --rm -e OPENROUTER_API_KEY jev-ra doctor
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JEV_RA_CHROME=/usr/bin/chromium \
    HOME=/home/jev \
    XDG_STATE_HOME=/home/jev/.local/state \
    XDG_CONFIG_HOME=/home/jev/.config

# chromium brings its own libraries; the fonts are what a page needs to lay itself out at all.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        ca-certificates \
        chromium \
        chromium-sandbox \
        fonts-liberation \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Chrome's own sandbox needs an unprivileged user, and root never has one.
RUN useradd --create-home --home-dir /home/jev --uid 10001 jev

WORKDIR /src
COPY pyproject.toml README.md LICENSE AGENTS.md ./
COPY jev_ra ./jev_ra
RUN pip install --no-cache-dir .

WORKDIR /home/jev
RUN rm -rf /src
USER jev

ENTRYPOINT ["jev-ra"]
CMD ["doctor"]
