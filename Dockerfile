FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/Adam-J-Roberts/Family-Stalker"
LABEL org.opencontainers.image.description="Family-Stalker health-only development scaffold"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/backend/server.py /app/server.py
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]
CMD ["python", "/app/server.py"]
