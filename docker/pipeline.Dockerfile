FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only code and configuration enter the image; data, runs, approved versions and MLflow
# storage are mounted as volumes.
COPY config.yaml .
COPY pipeline/ pipeline/

CMD ["python", "-m", "pipeline.run", "--config", "config.yaml"]
