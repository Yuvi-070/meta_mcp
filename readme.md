# Meta Marketing & Graph API MCP Server

A production-grade **Model Context Protocol (MCP)** server connecting **Google Gemini Enterprise**, **Vertex AI Agent Builder**, and local AI agents (**Antigravity**, **Claude Desktop**) directly to Meta's live **Marketing API & Graph API (v23.0)**.

Enables AI agents to query Facebook Pages, Instagram Business profiles, and Meta Ad Accounts in real-time using natural language.

---

## Key Features

- **Dual Transport Protocols**:
  - **Stdio Transport**: Zero-latency local execution for desktop developer agents (Antigravity IDE, Claude Desktop).
  - **Streamable HTTP (ASGI)**: Official MCP Streamable HTTP transport mounted at `/mcp` for Google Cloud Run and Gemini Enterprise.
- **Smart Dual-Token Routing**: Automatically routes **User Access Tokens** for Ad Accounts and Marketing endpoints, and dynamically resolves **Page Access Tokens** for Facebook and Instagram interactions.
- **Production Health Probes**: Built-in `/health` and `/` endpoints ready for GCP Cloud Run and Kubernetes health probes.
- **100% Live API Operations**: Real-time HTTP requests with comprehensive error handling, automatic token validation, and zero mock fallbacks.

---

## Tools Inventory (8 Production Tools)

### 1. Account Diagnostics & Connection
| Tool | Description | Target Endpoint |
| :--- | :--- | :--- |
| `meta_check_connection` | Tests token validity against `/me`, audits granted permissions, lists accessible ad accounts and administered Facebook pages. | `GET /v23.0/me`, `GET /me/accounts` |

### 2. Facebook Page & Content
| Tool | Description | Target Endpoint |
| :--- | :--- | :--- |
| `facebook_page_info` | Retrieves page name, category, followers, verification status, and page URL. | `GET /v23.0/{page_id}` |
| `facebook_posts` | Fetches recent posts with like counts, comments, reactions summary, and permalinks. | `GET /v23.0/{page_id}/posts` |
| `facebook_page_insights` | Audits page metrics (`page_post_engagements`, `page_daily_follows`, `page_views_total`). | `GET /v23.0/{page_id}/insights` |
| `facebook_publish_post` | Publishes status updates or links directly to the page feed. | `POST /v23.0/{page_id}/feed` |

### 3. Meta Marketing & Ad Accounts
| Tool | Description | Target Endpoint |
| :--- | :--- | :--- |
| `meta_ad_accounts` | Lists all ad accounts accessible by the authenticated user with status and currency. | `GET /v23.0/me/adaccounts` |
| `meta_ad_account_details` | Inspects real-time ad spend, balance, spend caps, currency (INR/USD), and account status. | `GET /v23.0/{ad_account_id}` |
| `meta_ad_campaigns` | Retrieves advertising campaigns, objectives, daily/lifetime budgets, and schedules. | `GET /v23.0/{ad_account_id}/campaigns` |
| `meta_ad_insights` | Returns performance metrics (impressions, clicks, spend, CPC, CPM, CTR, reach). | `GET /v23.0/{ad_account_id}/insights` |

### 4. Instagram Business Integration
| Tool | Description | Target Endpoint |
| :--- | :--- | :--- |
| `instagram_business_account` | Discovers connected Instagram Business profile, username, followers, and media count. | `GET /v23.0/{page_id}?fields=instagram_business_account` |
| `instagram_insights` | Queries profile views, impressions, and reach. | `GET /v23.0/{ig_user_id}/insights` |
| `instagram_recent_media` | Retrieves recent Instagram media posts, captions, likes, and comments. | `GET /v23.0/{ig_user_id}/media` |

---

## Quickstart & Local Setup

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Set your Meta credentials in `.env`:
```ini
# User Access Token (with ads_management, ads_read, pages_read_engagement, pages_show_list, instagram_basic)
META_ACCESS_TOKEN=XXX...

# Target Facebook Page ID
META_PAGE_ID=XXX...

# Optional: Dedicated Page Access Token (if omitted, resolved automatically via /me/accounts)
META_PAGE_ACCESS_TOKEN=XXX...

# Meta App Credentials
META_APP_ID=XXX...
META_APP_SECRET=XXX...

META_GRAPH_API_VERSION=v23.0
```

### 3. Running Locally

- **Stdio Mode (for Antigravity & Claude Desktop)**:
  ```bash
  python meta_mcp_server.py
  ```

- **HTTP Mode (Web Server on Port 8080)**:
  ```bash
  python meta_mcp_server.py --http
  # OR using uvicorn directly:
  uvicorn meta_mcp_server:app --host 0.0.0.0 --port 8080
  ```
  Test health check probe:
  ```bash
  curl http://localhost:8080/health
  # Response: {"status":"healthy","service":"meta-mcp-server","mcp_endpoint":"/mcp","transport":"streamable-http"}
  ```

---

## Antigravity Local Integration

Add the server to your Antigravity global MCP configuration at:  
`~/.gemini/config/mcp_config.json` (or project `.agents/mcp_config.json`):

```json
{
  "mcpServers": {
    "meta": {
      "command": "python",
      "args": [
        "c:\\path\\to\\meta mcp\\meta_mcp_server.py"
      ],
      "env": {
        "META_PAGE_ID": "XXX..."
      }
    }
  }
}
```

Once added, prompt Antigravity in chat:
- *"Check connection status for my Meta MCP server."*
- *"Show details for my Facebook Page and recent posts."*
- *"Audit our Meta ad account and show current spend."*

---

## Gemini Enterprise Cloud Integration

```
Gemini Enterprise / Vertex AI Agent Builder
      │ (Streamable HTTP / OAuth 2.0)
      ▼
Google Cloud Run (/mcp endpoint)
      │
      ├─► Secret Manager (META_ACCESS_TOKEN, META_PAGE_ID)
      ▼
Meta Graph API (https://graph.facebook.com/v23.0)
```

In **Gemini Enterprise**:
1. Navigate to **Data Stores > MCP Servers > Custom MCP Server**.
2. Select **OAuth 2.0** authentication method.
3. Configure the following parameters:

| Field | Production Value |
| :--- | :--- |
| **MCP Server URL** | `https://<your-cloud-run-service>.a.run.app/mcp` |
| **Authorization URL** | `https://www.facebook.com/v23.0/dialog/oauth` |
| **Authorization Parameters**| `&response_type=code` |
| **Token URL** | `https://graph.facebook.com/v23.0/oauth/access_token` |
| **Client ID** | `XXX...` |
| **Client Secret** | `XXX...` |
| **Scopes** | `ads_mcp_management ads_read pages_read_engagement pages_show_list instagram_basic` |

---

## Google Cloud Run Deployment

Deploy to Google Cloud Run in one command using the included deployment scripts:

### Windows PowerShell:
```powershell
.\deploy.ps1 -Region "asia-south1" -ServiceName "meta-mcp"
```

### Linux / macOS / Cloud Shell:
```bash
chmod +x deploy.sh
./deploy.sh asia-south1 meta-mcp
```

### Manual Deployment via gcloud CLI:
```bash
# 1. Store tokens securely in GCP Secret Manager
echo -n "XXX..." | gcloud secrets create meta-access-token --data-file=-
echo -n "XXX..." | gcloud secrets create meta-page-id --data-file=-

# 2. Deploy container to Cloud Run
gcloud run deploy meta-mcp \
  --source . \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --set-secrets="META_ACCESS_TOKEN=meta-access-token:latest,META_PAGE_ID=meta-page-id:latest" \
  --set-env-vars="MCP_TRANSPORT=streamable-http,PORT=8080"
```

---

## Core Repository Files

```
├── meta_mcp_server.py      # Primary MCP Server (FastMCP, Stdio + Streamable HTTP)
├── Dockerfile              # Production Python 3.12-slim container for Cloud Run
├── requirements.txt        # Pinned runtime dependencies
├── .dockerignore           # Container build exclusions
├── .gitignore              # Repository exclusions (secrets, tests, docs, assets)
├── .env.example            # Environment variables configuration template
├── deploy.ps1              # Windows PowerShell deployment automation
├── deploy.sh               # Unix/Cloud Shell deployment automation
└── readme.md               # Production documentation
```

---

## License

Internal Enterprise Tooling — Built for Meta Graph API & Gemini Enterprise Integration.
