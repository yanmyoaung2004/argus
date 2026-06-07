# Stage 1: Builder
FROM python:3.13-slim AS builder

WORKDIR /build

COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install build && \
    python -m build --wheel

# Stage 2: Production
FROM python:3.13-slim AS prod

WORKDIR /app

RUN groupadd -r argus && useradd -r -g argus argus

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

COPY argus/ argus/
COPY infra/ infra/

RUN mkdir -p /home/argus/.argus && \
    chown -R argus:argus /home/argus/.argus /app

USER argus

EXPOSE 8000

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "argus"]
