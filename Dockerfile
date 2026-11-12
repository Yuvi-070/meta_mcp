# Production Dockerfile for Meta MCP Server on Google Cloud Run
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr for real-time logs in GCP Cloud Logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY meta_mcp_server.py .

# Expose standard Cloud Run port
EXPOSE 8080

# Run uvicorn pointing to the ASGI application with dynamic PORT evaluation
CMD exec uvicorn meta_mcp_server:app --host 0.0.0.0 --port ${PORT:-8080}

