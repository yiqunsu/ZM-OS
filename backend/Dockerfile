FROM python:3.12.11-slim-bookworm
ARG APP_REVISION=unknown
ENV APP_REVISION=${APP_REVISION}
LABEL org.opencontainers.image.revision=${APP_REVISION}

WORKDIR /app
COPY requirements.txt requirements.lock .
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY . .
RUN mkdir -p /app/data/chat-attachments
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
