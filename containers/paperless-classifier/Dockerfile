FROM python:3-alpine

RUN apk add --no-cache ripgrep git libgcc libstdc++

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/anomalyco/opencode:latest /usr/local/bin/opencode /usr/local/bin/opencode

RUN uv pip install --system --break-system-packages \
  "paperless @ git+https://github.com/rcdailey/home-ops.git@main#subdirectory=scripts/paperless"

COPY . /workspace
RUN chmod +x /workspace/entrypoint.sh \
  && addgroup -g 1000 opencode && adduser -u 1000 -G opencode -D opencode \
  && chown -R 1000:1000 /workspace

USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["/workspace/entrypoint.sh"]
