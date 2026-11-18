import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from services.driver_gateway.app.driver_api import router as driver_api


class FakeCoreAPIClient:
    def __init__(self):
        self.request_args = None

    async def request(self, **kwargs):
        self.request_args = kwargs
        return httpx.Response(
            200,
            headers=[
                ("content-type", "application/json"),
                ("set-cookie", "access_token=access; Path=/; HttpOnly"),
                ("set-cookie", "refresh_token=refresh; Path=/auth; HttpOnly"),
            ],
            json={"user_id": "driver-1"},
        )


def test_auth_proxy_forwards_cookies_and_preserves_auth_cookies(monkeypatch):
    client = FakeCoreAPIClient()
    monkeypatch.setattr(driver_api, "core_api_client", client)

    async def receive():
        return {"type": "http.request", "body": b'{"identifier":"driver"}', "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/auth/login",
            "raw_path": b"/auth/login",
            "query_string": b"client=mobile",
            "headers": [
                (b"cookie", b"refresh_token=old"),
                (b"content-type", b"application/json"),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
        receive,
    )

    response = asyncio.run(driver_api.proxy_auth("login", request))

    assert client.request_args["url"] == "http://localhost:8000/auth/login"
    assert str(client.request_args["params"]) == "client=mobile"
    assert client.request_args["headers"]["cookie"] == "refresh_token=old"
    assert client.request_args["content"] == b'{"identifier":"driver"}'
    assert response.status_code == 200
    assert len(response.headers.getlist("set-cookie")) == 2


def test_auth_proxy_does_not_expose_customer_registration(monkeypatch):
    client = FakeCoreAPIClient()
    monkeypatch.setattr(driver_api, "core_api_client", client)

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/auth/register/customer",
            "raw_path": b"/auth/register/customer",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
        receive,
    )

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(driver_api.proxy_auth("register/customer", request))

    assert error_info.value.status_code == 404
    assert client.request_args is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "earnings"),
        ("GET", "payment-methods"),
        ("POST", "payment-methods"),
        ("PUT", f"payment-methods/{uuid4()}/preferred"),
    ],
)
def test_driver_finance_routes_are_allowlisted_and_forward_sessions(monkeypatch, method, path):
    client = FakeCoreAPIClient()
    monkeypatch.setattr(driver_api, "core_api_client", client)

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": f"/driver/{path}",
            "raw_path": f"/driver/{path}".encode(),
            "query_string": b"",
            "headers": [
                (b"cookie", b"access_token=driver-session"),
                (b"content-type", b"application/json"),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
        receive,
    )

    response = asyncio.run(driver_api.proxy_driver(path, request))

    assert response.status_code == 200
    assert client.request_args["url"] == f"http://localhost:8000/driver/{path}"
    assert client.request_args["headers"]["cookie"] == "access_token=driver-session"


def test_driver_finance_proxy_rejects_malformed_payment_method_id(monkeypatch):
    client = FakeCoreAPIClient()
    monkeypatch.setattr(driver_api, "core_api_client", client)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "http",
            "path": "/driver/payment-methods/not-a-uuid/preferred",
            "raw_path": b"/driver/payment-methods/not-a-uuid/preferred",
            "query_string": b"",
            "headers": [(b"cookie", b"access_token=driver-session")],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
        receive,
    )

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(
            driver_api.proxy_driver("payment-methods/not-a-uuid/preferred", request)
        )

    assert error_info.value.status_code == 404
    assert client.request_args is None
