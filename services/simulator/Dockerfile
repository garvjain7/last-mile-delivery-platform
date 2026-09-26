# Dockerfile for building World Simulator test process container.
# Black-box external client tester.

FROM python:3.11-slim

WORKDIR /app

COPY services/simulator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/simulator/app /app/services/simulator/app

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.simulator.app.main"]
