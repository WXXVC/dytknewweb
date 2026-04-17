FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEWWEB_DATA_DIR=/app/data \
    ENGINE_VOLUME_PATH=/app/Volume \
    ENGINE_API_BASE=http://host.docker.internal:5555 \
    ENGINE_API_TOKEN=

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY docker/nginx.single.conf /etc/nginx/sites-available/default
COPY docker/start-single.sh /usr/local/bin/start-single.sh

RUN chmod +x /usr/local/bin/start-single.sh

EXPOSE 8000

CMD ["/usr/local/bin/start-single.sh"]
