# Refs: T-A07 task 1.
# Adapted from Sitoi/dailycheckin#591 part B idea, integrated into single stack.
# Changes vs upstream: build context is the repo root (CI uses context ./ + file docker/Dockerfile);
# base image python:3.9-alpine (EOL) -> python:3.11-slim (image choice only, requires-python stays >=3.9);
# install from this fork's source instead of the upstream PyPI package.
FROM python:3.11-slim

WORKDIR /dailycheckin

COPY docker/start.sh /usr/local/bin

# Keep the upstream runtime structure: cron + Asia/Shanghai timezone
# (alpine -> slim: apk -> apt, busybox `crond` -> `cron` in docker/start.sh)
RUN set -ex \
    && apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && chmod +x /usr/local/bin/start.sh

# Install the fork from source (replaces upstream `pip install dailycheckin --upgrade` from PyPI).
# The console script lands in /usr/local/bin, so the old `--user` install + PATH symlink is dropped.
COPY requirements.txt setup.py pyproject.toml README.md /tmp/src/
COPY dailycheckin /tmp/src/dailycheckin
RUN pip install --no-cache-dir /tmp/src && rm -rf /tmp/src

# Bake a default crontab so bare `docker run` works without a host mount;
# docker-compose's ./cron/ volume mount overrides it when present.
COPY docker/crontab_list.sh /dailycheckin/cron/crontab_list.sh
RUN chmod +x /dailycheckin/cron/crontab_list.sh && mkdir -p /dailycheckin/logs

ENTRYPOINT ["start.sh"]
