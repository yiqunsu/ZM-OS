FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system filmos \
    && useradd --system --gid filmos --home-dir /app filmos

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=filmos:filmos . .
RUN mkdir -p /app/data/chat-attachments \
    && chown -R filmos:filmos /app/data

USER filmos

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
