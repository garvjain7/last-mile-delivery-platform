# Dockerfile for building Driver Gateway edge service container.
# THE SECURE DMZ EDGE — COMPLETELY DECOUPLED FROM POSTGRES.

FROM python:3.11-slim

WORKDIR /app

COPY services/driver_gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY streaming /app/streaming
COPY services/driver_gateway/app /app/services/driver_gateway/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "services.driver_gateway.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
