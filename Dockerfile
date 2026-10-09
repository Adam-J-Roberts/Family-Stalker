FROM node:22-bookworm-slim AS client
WORKDIR /client
COPY web/client/package.json web/client/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/client/*.mjs ./
RUN CLIENT_OUT=/out npm run build

FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/Adam-J-Roberts/Family-Stalker"
LABEL org.opencontainers.image.description="Family-Stalker household server setup"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir /data && chown 10001:10001 /data && chmod 0700 /data
COPY services/backend/app.py services/backend/manage.py services/backend/data_service.py services/backend/push_service.py /app/
COPY services/backend/static /app/static
COPY --from=client /out /app/static
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "16"]
