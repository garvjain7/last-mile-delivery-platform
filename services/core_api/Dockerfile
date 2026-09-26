# Dockerfile for building Core API microservice container.
# FORMERLY ORDERS API — The single entry point for Merchants/Staff.

FROM python:3.11-slim

WORKDIR /app

COPY services/core_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY db_models /app/db_models
COPY streaming /app/streaming
COPY services/core_api/app /app/services/core_api/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "services.core_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
