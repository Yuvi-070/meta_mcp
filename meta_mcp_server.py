import os
import sys
import logging
from typing import Any, Dict, Optional, Tuple
import httpx
from dotenv import load_dotenv
from starlette.responses import JSONResponse

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("meta-mcp-server")

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v23.0")
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

mcp = FastMCP("Meta MCP Server", stateless_http=True)

# Cache page access tokens retrieved dynamically from /me/accounts
_PAGE_TOKEN_CACHE: Dict[str, str] = {}


def get_user_token() -> str:
    """Retrieve the primary User Access Token."""
    return os.getenv("META_ACCESS_TOKEN", "").strip()


def get_page_credentials(page_id_override: str = "") -> Tuple[str, str]:
    """
    Resolve the target Page ID and the appropriate Page Access Token.
    If META_PAGE_ACCESS_TOKEN is provided, uses it directly.
    Otherwise queries /me/accounts with the user token to extract the page's token.
    """
    configured_pid = os.getenv("META_PAGE_ID", "").strip()
    target_id = page_id_override.strip() if page_id_override else configured_pid

    # 1. Check if direct page access token is configured
    direct_token = os.getenv("META_PAGE_ACCESS_TOKEN", "").strip()
    if direct_token:
        return target_id, direct_token

    # 2. Check cache
    if target_id and target_id in _PAGE_TOKEN_CACHE:
        return target_id, _PAGE_TOKEN_CACHE[target_id]

    # 3. Query /me/accounts dynamically using user token
    user_token = get_user_token()
    if user_token:
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{GRAPH_API_BASE}/me/accounts",
                    params={"access_token": user_token}
                )
                if resp.status_code == 200:
                    accounts = resp.json().get("data", [])
                    for acc in accounts:
                        acc_id = str(acc.get("id"))
                        acc_token = acc.get("access_token")
                        if acc_id and acc_token:
                            _PAGE_TOKEN_CACHE[acc_id] = acc_token

                    # Match specific page or default to first administered page
                    if target_id and target_id in _PAGE_TOKEN_CACHE:
                        return target_id, _PAGE_TOKEN_CACHE[target_id]
                    elif accounts:
                        first_id = str(accounts[0]["id"])
                        first_token = accounts[0]["access_token"]
                        _PAGE_TOKEN_CACHE[first_id] = first_token
                        return first_id, first_token
        except Exception as ex:
            logger.warning(f"Could not automatically resolve page access token: {ex}")

    # Fallback to user token
    return target_id, user_token


def meta_request(
    path: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    access_token: Optional[str] = None
) -> Dict[str, Any]:
    """Execute an HTTP request against the Meta Graph API with comprehensive error handling."""
    token = access_token or get_user_token()
    if not token or token.strip() in ("", "YOUR_META_TOKEN", "YOUR_ACCESS_TOKEN"):
        return {
            "error": "Missing Meta Access Token",
            "status": "unconfigured",
            "message": "Please configure META_ACCESS_TOKEN in your environment or .env file."
        }

    request_params = dict(params or {})
    request_params["access_token"] = token

    url = f"{GRAPH_API_BASE}/{path.lstrip('/')}"
    try:
        with httpx.Client(timeout=30.0) as client:
            if method.upper() == "POST":
                response = client.post(url, params=request_params, json=data)
            else:
                response = client.get(url, params=request_params)

            if response.status_code >= 400:
                try:
                    err_payload = response.json()
                except Exception:
                    err_payload = {"raw_text": response.text}
                return {
                    "error": "Meta Graph API error",
                    "status_code": response.status_code,
                    "details": err_payload
                }

            return response.json()
    except httpx.RequestError as exc:
        logger.error(f"Network error communicating with Meta Graph API: {exc}")
        return {
            "error": "Network error communicating with Meta API",
            "details": str(exc)
        }


# ==============================================================================
# MCP Tools: Connection & Account Diagnostics
# ==============================================================================

@mcp.tool()
def meta_check_connection() -> Dict[str, Any]:
    """
    Check the current Meta API configuration, verify token validity with /me,
    and report granted permissions, connected ad accounts, and administered Facebook pages.
    """
    user_token = get_user_token()
    if not user_token:
        return {
            "status": "unconfigured",
            "message": "META_ACCESS_TOKEN is not configured in .env or environment variables."
        }

    masked_token = f"{user_token[:8]}...{user_token[-6:]}" if len(user_token) > 15 else "Set"

    me_data = meta_request("me", params={"fields": "id,name,permissions,adaccounts"})
    if "error" in me_data:
        return {
            "status": "error",
            "token_preview": masked_token,
            "error": me_data
        }

    perms = [p["permission"] for p in me_data.get("permissions", {}).get("data", []) if p.get("status") == "granted"]
    ad_accs = [acc["id"] for acc in me_data.get("adaccounts", {}).get("data", [])]

    # Query administered pages
    pages_data = meta_request("me/accounts")
    pages_list = pages_data.get("data", []) if isinstance(pages_data, dict) else []

    configured_pid = os.getenv("META_PAGE_ID", "").strip()

    return {
        "status": "connected",
        "graph_api_version": GRAPH_API_VERSION,
        "token_preview": masked_token,
        "user": {
            "id": me_data.get("id"),
            "name": me_data.get("name")
        },
        "granted_permissions": perms,
        "connected_ad_accounts": ad_accs,
        "administered_pages": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "category": p.get("category"),
                "has_page_token": bool(p.get("access_token"))
            } for p in pages_list
        ],
        "configured_page_id": configured_pid or (pages_list[0]["id"] if pages_list else "None")
    }


# ==============================================================================
# MCP Tools: Facebook Page & Posts
# ==============================================================================

@mcp.tool()
def facebook_page_info(page_id: str = "") -> Dict[str, Any]:
    """
    Retrieve Facebook Page details including name, followers count, fan count, category, verification, and link.
    Args:
        page_id: Optional page ID. Defaults to configured META_PAGE_ID or first administered page.
    """
    target_id, page_token = get_page_credentials(page_id)
    if not target_id:
        return {"error": "No page_id specified and no administered page found."}

    fields = "id,name,about,category,followers_count,fan_count,verification_status,link,website"
    return meta_request(target_id, params={"fields": fields}, access_token=page_token)


@mcp.tool()
def facebook_posts(limit: int = 5, page_id: str = "") -> Dict[str, Any]:
    """
    Fetch recent posts published by the Facebook Page, including engagement metrics.
    Args:
        limit: Number of posts to retrieve (1-50, default is 5).
        page_id: Optional page ID. Defaults to configured META_PAGE_ID.
    """
    target_id, page_token = get_page_credentials(page_id)
    if not target_id:
        return {"error": "No page_id specified and no administered page found."}

    clamped_limit = max(1, min(limit, 50))
    fields = "id,message,created_time,permalink_url,shares,reactions.summary(total_count),comments.summary(total_count)"
    return meta_request(f"{target_id}/posts", params={"fields": fields, "limit": clamped_limit}, access_token=page_token)


@mcp.tool()
def facebook_page_insights(
    metrics: str = "page_post_engagements,page_daily_follows,page_views_total",
    period: str = "day",
    page_id: str = ""
) -> Dict[str, Any]:
    """
    Retrieve Facebook Page reach, impressions, and engagement metrics.
    Args:
        metrics: Comma-separated list of metrics (e.g. page_impressions,page_engaged_users).
        period: Time aggregation period ('day', 'week', or 'days_28'). Default: 'day'.
        page_id: Optional page ID. Defaults to configured META_PAGE_ID.
    """
    target_id, page_token = get_page_credentials(page_id)
    if not target_id:
        return {"error": "No page_id specified and no administered page found."}

    return meta_request(
        f"{target_id}/insights",
        params={"metric": metrics, "period": period},
        access_token=page_token
    )


@mcp.tool()
def facebook_publish_post(message: str, link: str = "", page_id: str = "") -> Dict[str, Any]:
    """
    Publish a new status update or link post to the Facebook Page feed.
    Args:
        message: The text content of the post.
        link: Optional URL to include/embed in the post.
        page_id: Optional page ID. Defaults to configured META_PAGE_ID.
    """
    target_id, page_token = get_page_credentials(page_id)
    if not target_id:
        return {"error": "No page_id specified and no administered page found."}

    payload: Dict[str, Any] = {"message": message}
    if link:
        payload["link"] = link

    return meta_request(f"{target_id}/feed", method="POST", params=payload, access_token=page_token)


# ==============================================================================
# MCP Tools: Meta Marketing / Ads API
# ==============================================================================

@mcp.tool()
def meta_ad_accounts() -> Dict[str, Any]:
    """
    List all Meta Ad Accounts accessible with the current access token.
    Returns account IDs, names, currency, and account status.
    """
    return meta_request("me/adaccounts", params={"fields": "id,account_id,name,account_status,currency,amount_spent"})


@mcp.tool()
def meta_ad_account_details(ad_account_id: str = "") -> Dict[str, Any]:
    """
    Retrieve comprehensive details for an Ad Account (status, currency, spend, spend cap, balance).
    Args:
        ad_account_id: Ad Account ID (e.g. 'act_1613858306623881'). Defaults to the first accessible ad account.
    """
    target_id = ad_account_id.strip()
    if not target_id:
        accs = meta_ad_accounts()
        data = accs.get("data", [])
        if not data:
            return {"error": "No ad accounts found for this token."}
        target_id = data[0]["id"]

    if not target_id.startswith("act_") and target_id.isdigit():
        target_id = f"act_{target_id}"

    fields = "id,name,account_status,currency,amount_spent,spend_cap,balance,timezone_name"
    return meta_request(target_id, params={"fields": fields})


@mcp.tool()
def meta_ad_campaigns(ad_account_id: str = "", limit: int = 10) -> Dict[str, Any]:
    """
    Retrieve advertising campaigns from an Ad Account.
    Args:
        ad_account_id: Ad Account ID (e.g. 'act_1613858306623881'). Defaults to first accessible ad account.
        limit: Max number of campaigns to return (1-50, default is 10).
    """
    target_id = ad_account_id.strip()
    if not target_id:
        accs = meta_ad_accounts()
        data = accs.get("data", [])
        if not data:
            return {"error": "No ad accounts found for this token."}
        target_id = data[0]["id"]

    if not target_id.startswith("act_") and target_id.isdigit():
        target_id = f"act_{target_id}"

    clamped_limit = max(1, min(limit, 50))
    fields = "id,name,status,objective,start_time,stop_time,daily_budget,lifetime_budget"
    return meta_request(f"{target_id}/campaigns", params={"fields": fields, "limit": clamped_limit})


@mcp.tool()
def meta_ad_insights(ad_account_id: str = "", date_preset: str = "last_30d") -> Dict[str, Any]:
    """
    Get aggregated advertising performance metrics (impressions, clicks, spend, cpc, cpm, ctr, reach).
    Args:
        ad_account_id: Ad Account ID. Defaults to first accessible ad account.
        date_preset: Date range ('today', 'yesterday', 'last_7d', 'last_30d', 'maximum'). Default: 'last_30d'.
    """
    target_id = ad_account_id.strip()
    if not target_id:
        accs = meta_ad_accounts()
        data = accs.get("data", [])
        if not data:
            return {"error": "No ad accounts found for this token."}
        target_id = data[0]["id"]

    if not target_id.startswith("act_") and target_id.isdigit():
        target_id = f"act_{target_id}"

    fields = "impressions,clicks,spend,cpc,cpm,ctr,reach"
    return meta_request(f"{target_id}/insights", params={"fields": fields, "date_preset": date_preset})


# ==============================================================================
# MCP Tools: Instagram Business Integration
# ==============================================================================

@mcp.tool()
def instagram_business_account(page_id: str = "") -> Dict[str, Any]:
    """
    Retrieve the Instagram Business Account linked to the Facebook Page.
    Args:
        page_id: Optional page ID. Defaults to configured META_PAGE_ID.
    """
    target_id, page_token = get_page_credentials(page_id)
    if not target_id:
        return {"error": "No page_id specified."}

    fields = "instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count}"
    return meta_request(target_id, params={"fields": fields}, access_token=page_token)


@mcp.tool()
def instagram_insights(
    metrics: str = "impressions,reach,profile_views",
    period: str = "day",
    ig_user_id: str = "",
    page_id: str = ""
) -> Dict[str, Any]:
    """
    Get profile insights (reach, impressions, profile views) for the connected Instagram Business account.
    Args:
        metrics: Comma-separated metrics ('impressions,reach,profile_views').
        period: Aggregation period ('day', 'week', 'days_28').
        ig_user_id: Optional Instagram Business User ID. If omitted, resolved from linked page.
        page_id: Optional page ID if ig_user_id is omitted.
    """
    target_ig = ig_user_id.strip() if ig_user_id else ""
    _, page_token = get_page_credentials(page_id)

    if not target_ig:
        ig_account = instagram_business_account(page_id=page_id)
        if "error" in ig_account:
            return ig_account
        ig_obj = ig_account.get("instagram_business_account")
        if not ig_obj or "id" not in ig_obj:
            return {
                "error": "No Instagram Business Account linked to this Facebook Page.",
                "details": ig_account
            }
        target_ig = ig_obj["id"]

    return meta_request(
        f"{target_ig}/insights",
        params={"metric": metrics, "period": period},
        access_token=page_token
    )


@mcp.tool()
def instagram_recent_media(limit: int = 5, ig_user_id: str = "", page_id: str = "") -> Dict[str, Any]:
    """
    Fetch recent media posts from the connected Instagram Business account.
    Args:
        limit: Number of media items to retrieve (1-50, default is 5).
        ig_user_id: Optional Instagram Business User ID. If omitted, resolved from linked page.
        page_id: Optional page ID.
    """
    target_ig = ig_user_id.strip() if ig_user_id else ""
    _, page_token = get_page_credentials(page_id)

    if not target_ig:
        ig_account = instagram_business_account(page_id=page_id)
        if "error" in ig_account:
            return ig_account
        ig_obj = ig_account.get("instagram_business_account")
        if not ig_obj or "id" not in ig_obj:
            return {
                "error": "No Instagram Business Account linked to this Facebook Page.",
                "details": ig_account
            }
        target_ig = ig_obj["id"]

    clamped_limit = max(1, min(limit, 50))
    fields = "id,caption,media_type,media_url,permalink,like_count,comments_count,timestamp"
    return meta_request(f"{target_ig}/media", params={"fields": fields, "limit": clamped_limit}, access_token=page_token)


# ==============================================================================
# MCP Resources
# ==============================================================================

@mcp.resource("meta://status")
def status_resource() -> Dict[str, Any]:
    """Resource returning the current status and connectivity of the Meta MCP server."""
    return meta_check_connection()


@mcp.resource("meta://page")
def page_resource() -> Dict[str, Any]:
    """Resource returning the configured Facebook Page profile."""
    return facebook_page_info()


@mcp.resource("meta://adaccounts")
def adaccounts_resource() -> Dict[str, Any]:
    """Resource returning connected ad accounts."""
    return meta_ad_accounts()


# ==============================================================================
# Streamable HTTP / ASGI Application for Gemini Enterprise & Cloud Run
# ==============================================================================

app = mcp.streamable_http_app()


@app.route("/health", methods=["GET"])
async def health_endpoint(request) -> JSONResponse:
    return JSONResponse({
        "status": "healthy",
        "service": "meta-mcp-server",
        "mcp_endpoint": "/mcp",
        "transport": "streamable-http"
    })


@app.route("/", methods=["GET"])
async def root_endpoint(request) -> JSONResponse:
    return JSONResponse({
        "service": "Meta MCP Server",
        "status": "running",
        "mcp_endpoint": "/mcp",
        "health_check": "/health",
        "documentation": "Connect Gemini Enterprise or Antigravity to the /mcp endpoint using Streamable HTTP."
    })


# ==============================================================================
# REST API Endpoints for Vertex AI Agent Builder & OpenAPI Tools
# ==============================================================================

@app.route("/api/facebook/page-info", methods=["GET"])
async def api_facebook_page_info(request) -> JSONResponse:
    page_id = request.query_params.get("page_id", "")
    data = facebook_page_info(page_id=page_id)
    return JSONResponse(data)


@app.route("/api/facebook/posts", methods=["GET"])
async def api_facebook_posts(request) -> JSONResponse:
    limit_str = request.query_params.get("limit", "5")
    limit = int(limit_str) if limit_str.isdigit() else 5
    page_id = request.query_params.get("page_id", "")
    data = facebook_posts(limit=limit, page_id=page_id)
    return JSONResponse(data)


@app.route("/api/meta/ad-accounts", methods=["GET"])
async def api_meta_ad_accounts(request) -> JSONResponse:
    data = meta_ad_accounts()
    return JSONResponse(data)


@app.route("/api/meta/ad-account-details", methods=["GET"])
async def api_meta_ad_account_details(request) -> JSONResponse:
    ad_account_id = request.query_params.get("ad_account_id", "")
    data = meta_ad_account_details(ad_account_id=ad_account_id)
    return JSONResponse(data)


@app.route("/api/meta/check-connection", methods=["GET"])
async def api_meta_check_connection(request) -> JSONResponse:
    data = meta_check_connection()
    return JSONResponse(data)


# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == "__main__":
    import uvicorn

    port_env = os.getenv("PORT")
    transport_env = os.getenv("MCP_TRANSPORT", "").lower()
    run_as_http = "--http" in sys.argv or transport_env in ("streamable-http", "http") or port_env is not None

    if run_as_http:
        port = int(port_env or 8080)
        host = os.getenv("HOST", "0.0.0.0")
        logger.info(f"Starting Meta MCP Streamable HTTP server on http://{host}:{port}/mcp")
        uvicorn.run(app, host=host, port=port)
    else:
        logger.info("Starting Meta MCP server in stdio transport mode...")
        mcp.run()
