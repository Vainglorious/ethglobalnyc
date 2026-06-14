FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN npm --prefix arc ci --omit=dev

ENV COLONY_API_RUNS_DIR=/data/runs
EXPOSE 8000

CMD ["sh", "-c", "uvicorn colony_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
