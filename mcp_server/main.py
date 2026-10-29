"""Dual-route FastMCP test server for CX Agent Studio (GECX) regional failover testing.

Exposes two MCP routes on a single Cloud Run service:
- /mcp1 (and /mcp1/): Simulates an unhealthy primary regional endpoint or API proxy
  rejection by returning HTTP 400 Bad Request on MCP session initialization.
- /mcp2 (and /mcp2/): Healthy secondary regional Streamable HTTP MCP endpoint
  exposing the verify_customer tool.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse


def verify_customer(customer_id: str) -> dict[str, Any]:
    """Verifies a banking customer's identity status by customer ID.

    Args:
        customer_id: The customer identifier (for example, CUST-101).

    Returns:
        A dictionary containing verification status and regional source metadata.
    """
    return {
        "status": "VERIFIED",
        "customer_id": customer_id,
        "region": "europe-west1-secondary",
        "source": "mcp2-healthy-endpoint",
    }


async def unhealthy_primary_mcp(request: Request) -> PlainTextResponse:
    """Simulates an upstream proxy or primary region returning HTTP 400 Bad Request."""
    return PlainTextResponse("Bad Request", status_code=400)


async def healthz(request: Request) -> JSONResponse:
    """Returns HTTP 200 health status for container readiness probes."""
    return JSONResponse({"status": "ok"})


class TrailingSlashNormalizerMiddleware:
    """Rewrites /mcp2/ to /mcp2 in-place without issuing an HTTP 307 redirect."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path in ("/mcp2/", "/mcp2/mcp", "/mcp2/mcp/"):
                scope = dict(scope)
                scope["path"] = "/mcp2"
                scope["raw_path"] = b"/mcp2"
        await self.app(scope, receive, send)


def create_app() -> TrailingSlashNormalizerMiddleware:
    """Creates a fresh dual-route FastMCP ASGI application instance."""
    # Bind host="0.0.0.0" so FastMCP does not enable localhost-only DNS rebinding
    # checks when deployed behind a Cloud Run or internal load balancer hostname.
    mcp = FastMCP(
        "customer_idv_mcp",
        host="0.0.0.0",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp2",
    )
    mcp.tool()(verify_customer)

    base_app = mcp.streamable_http_app()
    base_app.add_route("/mcp1", unhealthy_primary_mcp, methods=["GET", "POST", "DELETE"])
    base_app.add_route("/mcp1/", unhealthy_primary_mcp, methods=["GET", "POST", "DELETE"])
    base_app.add_route("/health", healthz, methods=["GET"])
    base_app.add_route("/healthz", healthz, methods=["GET"])
    return TrailingSlashNormalizerMiddleware(base_app)


app = create_app()
