# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src/ src/
RUN uv build --wheel --out-dir /build/dist


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 secondbrain \
    && useradd --system --uid 1000 --gid secondbrain \
         --home-dir /home/secondbrain --create-home --shell /usr/sbin/nologin \
         secondbrain

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

USER secondbrain
WORKDIR /home/secondbrain

RUN mkdir -p /home/secondbrain/.config/second-brain \
             /home/secondbrain/.local/share/second-brain

ENTRYPOINT ["second-brain"]
CMD ["run"]
