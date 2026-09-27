FROM python:3.12.11-slim-bookworm
WORKDIR /app
COPY requirements.txt requirements.lock .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --timeout 60 --retries 5 -r requirements.txt -c requirements.lock
COPY . .
ARG APP_REVISION=unknown
ENV APP_REVISION=${APP_REVISION}
LABEL org.opencontainers.image.revision=${APP_REVISION}
RUN mkdir -p /app/data/chat-attachments
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
