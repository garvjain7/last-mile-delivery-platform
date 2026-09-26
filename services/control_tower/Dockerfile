# Dockerfile for building Control Tower live dashboard service container.
# LOW-LATENCY LIVE DASHBOARD SERVICE — No Postgres access.

FROM python:3.11-slim

WORKDIR /app

COPY services/control_tower/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY streaming /app/streaming
COPY services/control_tower/app /app/services/control_tower/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "services.control_tower.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
