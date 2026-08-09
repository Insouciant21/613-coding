FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY packaging ./packaging
COPY scripts/build_artifacts.sh ./scripts/build_artifacts.sh

RUN apt-get update \
    && apt-get install --no-install-recommends -y binutils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.8.14 \
    && uv sync --frozen \
    && ./scripts/build_artifacts.sh /out

FROM scratch AS artifacts
COPY --from=builder /out/ /
