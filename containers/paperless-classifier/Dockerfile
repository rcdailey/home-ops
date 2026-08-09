FROM python:3.14-alpine

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY classifier.py ./

RUN uv sync --script classifier.py \
    && addgroup -g 1000 classifier \
    && adduser -u 1000 -G classifier -D classifier \
    && chown -R 1000:1000 /app /opt/uv-cache

USER 1000:1000

ENTRYPOINT ["uv", "run", "--offline", "--script", "/app/classifier.py"]
