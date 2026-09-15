FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin analytics \
    && mkdir /data && chown analytics /data
COPY --chown=analytics:analytics analytics ./analytics
USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ANALYTICS_DB=/data/analytics.sqlite
EXPOSE 8000
CMD ["uvicorn", "analytics.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
