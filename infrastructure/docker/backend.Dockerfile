FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.17
COPY backend/pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY backend/ ./
RUN uv pip install --system --no-deps . && useradd --create-home --uid 1000 app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

# Worker image: adds headless Chromium for the opt-in scrapers (SCRAPING_ENABLED=true).
FROM base AS worker
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN uv pip install --system "playwright>=1.48" && playwright install --with-deps chromium     && chmod -R a+rx /ms-playwright && rm -rf /var/lib/apt/lists/*
USER app
HEALTHCHECK NONE
CMD ["celery", "-A", "app.workers.celery_app", "worker", "-Q", "research,default,notify", "-l", "info"]

# Login browser: headed Chromium on a TigerVNC display, streamed to the dashboard through noVNC (:6080).
# Used only when the user links a social account from Settings; the API controls it on :7900.
FROM worker AS login-browser
USER root
RUN apt-get update && apt-get install -y --no-install-recommends tigervnc-standalone-server tigervnc-tools         novnc websockify fonts-noto-core fonts-noto-color-emoji     && rm -rf /var/lib/apt/lists/*
COPY infrastructure/docker/login-browser-entrypoint.sh /usr/local/bin/login-browser-entrypoint
RUN chmod +x /usr/local/bin/login-browser-entrypoint
USER app
EXPOSE 6080 7900
CMD ["login-browser-entrypoint"]
