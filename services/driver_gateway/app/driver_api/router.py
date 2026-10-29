"""Driver-facing API proxy; database-backed operations remain owned by Core API."""

import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from services.driver_gateway.app.config import config

logger = logging.getLogger(__name__)
router = APIRouter()
core_api_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    follow_redirects=False,
)
_FORWARDED_REQUEST_HEADERS = ("accept", "authorization", "content-type", "cookie")
_FORWARDED_RESPONSE_HEADERS = (
    "cache-control",
    "content-disposition",
    "content-type",
    "etag",
    "last-modified",
    "location",
)
_AUTH_ENDPOINTS = {
    ("GET", "me"),
    ("POST", "forgot-password"),
    ("POST", "login"),
    ("POST", "logout"),
    ("POST", "refresh"),
    ("POST", "register/driver"),
    ("POST", "reset-password"),
}
_DRIVER_ENDPOINTS = {
    ("GET", "profile"),
    ("PATCH", "profile"),
    ("GET", "vehicles"),
    ("PUT", "vehicle"),
    ("GET", "routes"),
}


async def close_core_api_client() -> None:
    await core_api_client.aclose()


async def _forward_to_core_api(
    request: Request,
    namespace: str,
    path: str,
) -> Response:
    """Forward only the driver's auth and self-service API namespaces."""
    if namespace == "auth":
        is_allowed = (request.method, path) in _AUTH_ENDPOINTS
    else:
        route_parts = path.split("/")
        is_accept_route = (
            request.method == "POST"
            and len(route_parts) == 3
            and route_parts[0] == "routes"
            and route_parts[2] == "accept"
        )
        is_scan_route = (
            request.method == "POST"
            and len(route_parts) == 3
            and route_parts[0] == "routes"
            and route_parts[2] == "scan"
        )
        is_pod_authorize_route = (
            request.method == "POST"
            and len(route_parts) == 5
            and route_parts[0] == "routes"
            and route_parts[2] == "stops"
            and route_parts[4] == "pod-authorize"
        )
        if is_accept_route or is_scan_route:
            try:
                UUID(route_parts[1])
            except ValueError:
                is_accept_route = False
                is_scan_route = False
        if is_pod_authorize_route:
            try:
                UUID(route_parts[1])
                UUID(route_parts[3])
            except ValueError:
                is_pod_authorize_route = False
        is_allowed = (
            (request.method, path) in _DRIVER_ENDPOINTS
            or is_accept_route
            or is_scan_route
            or is_pod_authorize_route
        )
    if not is_allowed:
        raise HTTPException(status_code=404, detail="Driver API endpoint not found.")

    upstream_url = f"{config.core_api_url}/{namespace}/{path}"
    headers = {
        name: request.headers[name]
        for name in _FORWARDED_REQUEST_HEADERS
        if name in request.headers
    }

    try:
        upstream = await core_api_client.request(
            method=request.method,
            url=upstream_url,
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        logger.warning("Core API request timed out for %s/%s", namespace, path)
        raise HTTPException(status_code=504, detail="Driver API timed out.") from exc
    except httpx.RequestError as exc:
        logger.exception("Could not reach Core API for %s/%s", namespace, path)
        raise HTTPException(status_code=502, detail="Driver API is unavailable.") from exc

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={
            name: upstream.headers[name]
            for name in _FORWARDED_RESPONSE_HEADERS
            if name in upstream.headers
        },
    )
    for cookie in upstream.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", cookie)
    return response


@router.api_route(
    "/auth/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy_auth(path: str, request: Request) -> Response:
    return await _forward_to_core_api(request, "auth", path)


@router.api_route(
    "/driver/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy_driver(path: str, request: Request) -> Response:
    return await _forward_to_core_api(request, "driver", path)
