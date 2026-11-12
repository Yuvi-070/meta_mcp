#!/usr/bin/env bash
# Deployment script for Google Cloud Run (Linux / macOS / Cloud Shell)
set -e

REGION="${1:-asia-south1}"
SERVICE_NAME="${2:-meta-mcp}"

echo "=== Deploying Meta MCP Server to Google Cloud Run ==="
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars="MCP_TRANSPORT=streamable-http"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format 'value(status.url)')

echo ""
echo "=== Deployment Successful! ==="
echo "Service URL: $SERVICE_URL"
echo "Streamable HTTP MCP Endpoint: $SERVICE_URL/mcp"
echo "Health Check: $SERVICE_URL/health"
echo ""
echo "Register in Gemini Enterprise / Vertex AI Agent Builder with:"
echo "{"
echo "  \"name\": \"Meta MCP\","
echo "  \"transport\": {"
echo "    \"type\": \"streamable-http\","
echo "    \"url\": \"$SERVICE_URL/mcp\""
echo "  }"
echo "}"

