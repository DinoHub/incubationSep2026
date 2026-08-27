# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every runnable file has to be copied in before the first build, the test
# script included — the compose services below run them from the image.
COPY doc_tools_server.py http_server.py test_server.py healthcheck.py ./
COPY auth.py test_auth.py ./
COPY seed_data.py ./

RUN useradd --create-home appuser && chown -R appuser /app
RUN mkdir -p /app/documents && chown -R appuser /app/documents
USER appuser

EXPOSE 8000
CMD ["python", "http_server.py"]
