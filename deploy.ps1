# Windows PowerShell Deployment Script for Google Cloud Run
param(
    [string]$Region = "asia-south1",
    [string]$ServiceName = "meta-mcp",
    [string]$ProjectId = ""
)

Write-Host "=== Deploying Meta MCP Server to Google Cloud Run ===" -ForegroundColor Cyan

# Set Project if provided
if ($ProjectId) {
    gcloud config set project $ProjectId
}

# Check if .env exists
if (Test-Path ".env") {
    Write-Host "Found .env file. Note: For Cloud Run, secrets should be stored in GCP Secret Manager." -ForegroundColor Yellow
}

# Deploy to Cloud Run
Write-Host "Deploying service '$ServiceName' in region '$Region'..." -ForegroundColor Green

gcloud run deploy $ServiceName `
    --source . `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --set-env-vars="MCP_TRANSPORT=streamable-http,PORT=8080"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n=== Deployment Successful! ===" -ForegroundColor Green
    $ServiceUrl = (gcloud run services describe $ServiceName --region $Region --format 'value(status.url)')
    Write-Host "Service URL: $ServiceUrl" -ForegroundColor Cyan
    Write-Host "Streamable HTTP MCP Endpoint: $ServiceUrl/mcp" -ForegroundColor Cyan
    Write-Host "Health Check: $ServiceUrl/health" -ForegroundColor Cyan
    Write-Host "`nRegister in Gemini Enterprise / Vertex AI Agent Builder with:" -ForegroundColor White
    Write-Host "{`n  `"name`": `"Meta MCP`",`n  `"transport`": {`n    `"type`": `"streamable-http`",`n    `"url`": `"$ServiceUrl/mcp`"`n  }`n}" -ForegroundColor Yellow
}
else {
    Write-Host "Deployment failed. Please verify gcloud credentials." -ForegroundColor Red
}

