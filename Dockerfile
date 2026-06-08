FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FILEDROP_INSTANCE_PATH=/data/instance
ENV FILEDROP_UPLOAD_PATH=/data/uploads

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/instance /data/uploads
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2); payload = json.load(response); raise SystemExit(0 if response.status == 200 and payload.get('status') == 'ok' else 1)"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--threads", "16", "--timeout", "0", "app:app"]
