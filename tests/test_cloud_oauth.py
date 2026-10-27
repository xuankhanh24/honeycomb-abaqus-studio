import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from honeycomb_studio import cloud_api
from honeycomb_studio.cloud_api import create_app

CANONICAL = "https://honeycomb-abaqus-studio.vercel.app"
ALIAS = "https://web-swart-phi-64.vercel.app"


def configure(monkeypatch):
    monkeypatch.delenv("WEB_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-oauth-session-secret")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test-only-client-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test-only-client-secret")


def test_alias_login_moves_to_registered_origin_before_creating_oauth_state(monkeypatch):
    configure(monkeypatch)
    with TestClient(create_app(), base_url=ALIAS) as client:
        response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == CANONICAL + "/auth/login"
    assert "session=" not in response.headers.get("set-cookie", "")


def test_production_login_sends_registered_https_callback_and_keeps_state(monkeypatch):
    configure(monkeypatch)
    with TestClient(create_app(), base_url=CANONICAL) as client:
        response = client.get("/auth/login", follow_redirects=False)
    target = urlsplit(response.headers["location"])
    assert target.scheme == "https" and target.netloc == "github.com"
    query = parse_qs(target.query)
    assert query["redirect_uri"] == [CANONICAL + "/auth/callback"]
    assert query["state"][0] and "session=" in response.headers["set-cookie"]


def test_callback_exchanges_the_same_canonical_uri_and_establishes_owner_session(monkeypatch):
    configure(monkeypatch)
    real_client = httpx.Client
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/login/oauth/access_token":
            body = json.loads(request.content)
            assert body["redirect_uri"] == CANONICAL + "/auth/callback"
            return httpx.Response(200, json={"access_token": "test-only-access-token"})
        assert request.url.path == "/user"
        return httpx.Response(200, json={"id": cloud_api.OWNER_ID})

    monkeypatch.setattr(cloud_api.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    with TestClient(create_app(), base_url=CANONICAL) as client:
        login = client.get("/auth/login", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        callback = client.get("/auth/callback", params={"code": "test-only-code", "state": state}, follow_redirects=False)
        assert callback.status_code == 303
        assert client.get("/api/session").json()["owner"] is True
        assert client.get("/auth/callback", params={"code": "test-only-code", "state": state}).status_code == 403
    assert calls == ["/login/oauth/access_token", "/user"]


def test_alias_callback_does_not_forward_authorization_code(monkeypatch):
    configure(monkeypatch)
    with TestClient(create_app(), base_url=ALIAS) as client:
        response = client.get("/auth/callback", params={"code": "test-only-code", "state": "untrusted-state"}, follow_redirects=False)
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize("origin", ["http://example.test", "https://user:secret@example.test", "https://example.test/path", "https://example.test?query=1"])
def test_invalid_canonical_origin_is_rejected(monkeypatch, origin):
    monkeypatch.setenv("WEB_PUBLIC_ORIGIN", origin)
    with pytest.raises(ValueError, match="origin HTTPS"):
        create_app()
