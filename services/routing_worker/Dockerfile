# Dockerfile for building Routing Worker isolated compute engine.
# ISOLATED COMPUTE ENGINE — No HTTP endpoints, pure consumer loop.

FROM python:3.11-slim

WORKDIR /app

COPY services/routing_worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY db_models /app/db_models
COPY streaming /app/streaming
COPY services/routing_worker/app /app/services/routing_worker/app

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.routing_worker.app.main"]
