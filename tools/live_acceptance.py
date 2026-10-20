#!/usr/bin/env python3
"""Production acceptance test for deployed Samraksha Kendra web MVP.

Does not print secrets, modify review decisions, or insert surveillance rows.
It sends only one labelled synthetic WebSocket notification to currently
connected recipients, via the dedicated demo endpoint.
"""
from __future__ import annotations

import asyncio
import getpass
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

API_DEFAULT = "https://samraksha-kendra-api.onrender.com"


def valid_api_base(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.netloc.startswith("postgres")


def request_json(base: str, path: str, method: str = "GET", token: str | None = None, payload=None, timeout: int = 45):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        try:
            value = json.loads(content)
        except ValueError:
            value = {"detail": content[:200]}
        return exc.code, value
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {"detail": "Network request failed; check service status and API URL."}


def pass_check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    return condition


async def websocket_demo_test(base: str, token: str) -> tuple[bool, str]:
    try:
        import websockets
    except ImportError:
        return False, "Install websockets in this local venv to test the live notification."
    parsed = urlparse(base)
    ws_url = f"{'wss' if parsed.scheme == 'https' else 'ws'}://{parsed.netloc}/ws/alerts"
    try:
        async with websockets.connect(ws_url, open_timeout=20, close_timeout=5, ping_interval=20) as ws:
            await ws.send(json.dumps({"type": "authenticate", "token": token}))
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if ready.get("type") != "connection_ready":
                return False, "WebSocket authentication handshake did not return connection_ready."
            status, result = await asyncio.to_thread(request_json, base, "/analytics/demo-anomaly", "POST", token, {})
            if status != 200:
                return False, f"Synthetic-event endpoint returned HTTP {status}."
            delivered = int(result.get("delivered_clients", 0) or 0)
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if event.get("type") != "demo_anomaly" or event.get("is_synthetic") is not True:
                return False, "Expected labelled synthetic event was not received."
            if delivered < 1:
                return False, "Server reported no connected recipients for the demo event."
            return True, "Authenticated WebSocket received a labelled synthetic event; no surveillance rows were inserted."
    except Exception as exc:
        return False, f"WebSocket check failed: {type(exc).__name__}."


def main() -> int:
    while True:
        base = input(f"API base URL [{API_DEFAULT}] (press Enter for default): ").strip() or API_DEFAULT
        if valid_api_base(base):
            base = base.rstrip("/")
            break
        print("Invalid API base URL. Enter the HTTPS API address only, not a database URL.")

    status, root = request_json(base, "/", timeout=75)
    ok = True
    ok &= pass_check("API root", status == 200 and root.get("status") == "running", f"HTTP {status}")
    status, schema = request_json(base, "/openapi.json")
    paths = schema.get("paths", {}) if isinstance(schema, dict) else {}
    required_routes = [
        "/auth/login", "/hospitals/count", "/public/surveillance/summary",
        "/system/source-status", "/admin/ncdc-report-queue",
        "/admin/ncdc-report-queue/audit", "/admin/ncdc-staging/summary",
        "/analytics/anomalies", "/analytics/demo-anomaly",
    ]
    routes_ok = status == 200 and all(route in paths for route in required_routes)
    ok &= pass_check("Required API routes including review audit", routes_ok, f"{len(paths)} documented API paths")

    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password (hidden; never paste it into chat): ")
    status, login = request_json(base, "/auth/login", "POST", payload={"username": username, "password": password})
    password = ""
    token = (login.get("access_token") or login.get("token") or login.get("accessToken")) if isinstance(login, dict) else None
    ok &= pass_check("Admin login", status == 200 and bool(token), f"HTTP {status}")
    if status != 200 or not token:
        print("Login failed; no token or credential values were printed.")
        return 1

    checks = [
        ("Hospital directory", "/hospitals/count", lambda x: int(x.get("count", 0)) > 0, "count"),
        ("Surveillance summary", "/public/surveillance/summary", lambda x: int(x.get("total_records", 0)) > 0, "total_records"),
        ("Official source status", "/system/source-status", lambda x: isinstance(x.get("sources"), list) and len(x["sources"]) >= 2, "sources"),
        ("NCDC review queue", "/admin/ncdc-report-queue", lambda x: isinstance(x.get("items"), list) and isinstance(x.get("total"), int), "total"),
        ("Review audit history", "/admin/ncdc-report-queue/audit?limit=10", lambda x: isinstance(x.get("items"), list) and isinstance(x.get("count"), int), "count"),
        ("NCDC staging preview", "/admin/ncdc-staging/summary", lambda x: isinstance(x.get("status_counts"), dict) and isinstance(x.get("total_records"), int), "total_records"),
        ("Anomaly screening", "/analytics/anomalies", lambda x: isinstance(x.get("items"), list) and isinstance(x.get("diagnostics"), dict), "status"),
    ]
    for label, path, validator, key in checks:
        status, body = request_json(base, path, token=token)
        valid = status == 200 and validator(body)
        detail = f"HTTP {status}"
        if status == 200:
            detail += f", {key}={body.get(key)}"
        ok &= pass_check(label, valid, detail)

    try:
        ws_ok, detail = asyncio.run(websocket_demo_test(base, token))
    except RuntimeError:
        ws_ok, detail = False, "Could not run the asynchronous WebSocket check in this Python process."
    ok &= pass_check("Synthetic live notification", ws_ok, detail)
    print("\nFINAL RESULT:", "CORE MVP ACCEPTANCE PASSED" if ok else "CORE MVP ACCEPTANCE HAS FAILURES")
    print("Scope note: mobile, RAG chatbot, MobileNetV2 image model, full multilingual coverage and robust automatic PDF reconciliation are not certified by this web-MVP test.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
