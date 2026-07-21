FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY packages/database ./packages/database
COPY apps/api ./apps/api

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir ./packages/database ./apps/api

FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"
ENV APP_ENV=local
ENV API_HOST=0.0.0.0
ENV API_PORT=4000
ENV LOG_LEVEL=INFO
ENV ALLOWED_FRONTEND_ORIGINS=http://localhost:3000
ENV DATABASE_ECHO=false

WORKDIR /app

RUN addgroup --system app \
  && adduser --system --ingroup app app

COPY --from=builder /opt/venv /opt/venv

USER app

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health', timeout=3).read()" || exit 1

CMD ["sh", "-c", "uvicorn labelos_api.main:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-4000}"]
