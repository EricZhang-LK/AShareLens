# syntax=docker/dockerfile:1.7

FROM node:25-bookworm-slim AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 asharelens \
    && useradd --system --uid 10001 --gid asharelens \
       --home-dir /app --shell /usr/sbin/nologin asharelens

WORKDIR /app
COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY --from=web-build /build/web/dist ./src/asharelens/server/static

RUN python -m pip install ".[server,data]" \
    && chown -R asharelens:asharelens /app

USER asharelens
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).read()"]

CMD ["asharelens", "web", "--host", "0.0.0.0", "--port", "8000", "--allow-network"]
