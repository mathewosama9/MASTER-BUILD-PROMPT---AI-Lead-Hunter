FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /bot
COPY telegram/pyproject.toml ./
RUN pip install --no-cache-dir "aiogram[redis]>=3.13" "httpx>=0.27" "pydantic-settings>=2.4" "aiohttp>=3.9"
COPY telegram/ ./
RUN useradd --create-home --uid 1000 bot && chown -R bot /bot
USER bot
EXPOSE 8081
CMD ["python", "main.py"]
