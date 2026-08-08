FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.14 \
    && uv sync --frozen --no-dev
COPY src ./src
COPY docker/entrypoint.sh /usr/local/bin/613-entrypoint
RUN useradd --create-home --uid 10001 coding \
    && chmod 0755 /usr/local/bin/613-entrypoint \
    && chown -R coding:coding /app

USER coding
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
ENTRYPOINT ["/usr/local/bin/613-entrypoint"]
