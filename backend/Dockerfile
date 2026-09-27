FROM python:3.12.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system filmos \
    && useradd --system --gid filmos --home-dir /app filmos

COPY requirements.txt requirements.lock ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --index-url "${PIP_INDEX_URL}" --timeout 60 --retries 5 -r requirements.txt -c requirements.lock

COPY --chown=filmos:filmos . .
ARG APP_REVISION=unknown
ENV APP_REVISION=${APP_REVISION}
LABEL org.opencontainers.image.revision=${APP_REVISION}
RUN mkdir -p /app/data/chat-attachments \
    && chown -R filmos:filmos /app/data

EXPOSE 8000

# Preserve local volume ownership; production runs as the dedicated user.
FROM base AS local
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS production
USER filmos

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
