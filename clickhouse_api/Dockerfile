FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY clickhouse_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app code + the repo clickhouse/.env fallback path are copied by the build context
COPY clickhouse_api ./clickhouse_api
COPY clickhouse ./clickhouse

EXPOSE 8009

# CLICKHOUSE_* should be provided as env vars in prod (don't bake the .env into the image)
CMD ["sh", "-c", "uvicorn main:app --app-dir clickhouse_api --host 0.0.0.0 --port ${PORT:-8009}"]
