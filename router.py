#!/usr/bin/env python3
"""
Router proxy that dispatches requests to three backend servers on a single ngrok domain.

Usage:
    python router.py --port 3000

The router listens on port 3000 and routes requests based on the path prefix:
  /scheduler/* → localhost:3001
  /agent-connect/* → localhost:3002
  /event-ingestor/* → localhost:3003

Alternative routing based on Host header is also supported for incoming requests
with Host: scheduler.localhost, agent-connect.localhost, etc.
"""

import argparse
import logging
import sys
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

BACKENDS = {
    "scheduler": "http://localhost:3001",
    "agent-connect": "http://localhost:3002",
    "event-ingestor": "http://localhost:3003",
}


def get_backend(request: Request) -> Optional[tuple[str, str]]:
    """Determine backend based on path prefix or Host header."""
    path = request.url.path
    host = request.headers.get("host", "").lower()

    # Route by path prefix (highest priority)
    for prefix, backend_name in [
        ("/scheduler", "scheduler"),
        ("/agent-connect", "agent-connect"),
        ("/event-ingestor", "event-ingestor"),
    ]:
        if path.startswith(prefix):
            return backend_name, BACKENDS[backend_name]

    # Route by Host header subdomain (fallback)
    if host:
        for backend_name, backend_url in BACKENDS.items():
            if host.startswith(backend_name):
                return backend_name, backend_url

    # Default: no valid route
    return None


async def forward_request(request: Request, backend_url: str) -> StreamingResponse:
    """Forward request to backend and stream response."""
    # Build backend URL: strip prefix if present
    path = request.url.path
    query = request.url.query

    # Remove the service prefix from path if it exists
    for service in BACKENDS.keys():
        prefix = f"/{service}"
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break

    # Ensure path starts with /
    if not path:
        path = "/"

    target_url = f"{backend_url}{path}"
    if query:
        target_url += f"?{query}"

    logger.info(f"Routing {request.method} {request.url.path} -> {target_url}")

    # Read request body if present
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Forward headers, excluding host
            headers = dict(request.headers)
            headers.pop("host", None)

            response = await client.request(
                method=request.method,
                url=target_url,
                content=body if body else None,
                headers=headers,
                follow_redirects=True,
            )

            return StreamingResponse(
                content=response.aiter_bytes(),
                status_code=response.status_code,
                headers=dict(response.headers),
            )
    except Exception as e:
        logger.error(f"Error forwarding request: {e}")
        return StreamingResponse(
            content=[b"502 Bad Gateway"],
            status_code=502,
        )


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def router(request: Request, path: str):
    """Main router endpoint."""
    result = get_backend(request)

    if not result:
        logger.warning(f"No backend found for {request.url.path}")
        return StreamingResponse(
            content=[b"404 Not Found: Service not found. Use /scheduler, /agent-connect, or /event-ingestor"],
            status_code=404,
        )

    backend_name, backend_url = result
    logger.debug(f"Routing to {backend_name} ({backend_url})")
    return await forward_request(request, backend_url)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Root endpoint with routing info."""
    return {
        "service": "Router",
        "version": "1.0.0",
        "backends": BACKENDS,
        "usage": "Route requests to /scheduler/*, /agent-connect/*, or /event-ingestor/*",
    }


def main():
    parser = argparse.ArgumentParser(description="Router proxy for three backend servers")
    parser.add_argument("--port", type=int, default=3000, help="Port to listen on (default: 3000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    args = parser.parse_args()

    logger.info(f"Starting router on {args.host}:{args.port}")
    logger.info(f"Backends: {BACKENDS}")

    uvicorn.run(
        "router:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
