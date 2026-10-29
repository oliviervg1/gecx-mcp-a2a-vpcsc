"""Offline unit tests for the dual-route FastMCP test server."""

import json
from pathlib import Path
import sys

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
import main as mcp_main  # noqa: E402


def test_healthz_returns_200() -> None:
    with TestClient(mcp_main.create_app()) as client:
        for path in ("/health", "/healthz"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


def test_mcp1_unhealthy_route_returns_400_bad_request() -> None:
    with TestClient(mcp_main.create_app()) as client:
        for path in ("/mcp1", "/mcp1/"):
            resp = client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert resp.status_code == 400
            assert resp.text == "Bad Request"


def test_mcp2_healthy_route_accepts_trailing_slash_without_redirect() -> None:
    with TestClient(mcp_main.create_app()) as client:
        resp = client.post(
            "/mcp2/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-client", "version": "1.0.0"},
                },
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["serverInfo"]["name"] == "customer_idv_mcp"


def test_mcp2_tools_call_verify_customer_returns_verified_record() -> None:
    with TestClient(mcp_main.create_app()) as client:
        resp = client.post(
            "/mcp2/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "verify_customer",
                    "arguments": {"customer_id": "CUST-101"},
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        record = json.loads(body["result"]["content"][0]["text"])
        assert record == {
            "status": "VERIFIED",
            "customer_id": "CUST-101",
            "region": "europe-west1-secondary",
            "source": "mcp2-healthy-endpoint",
        }
