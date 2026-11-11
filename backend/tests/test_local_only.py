import pytest
from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app(), base_url="http://localhost")


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:5173", "[::1]:8000"])
def test_local_host_is_allowed(host):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "[bad"])
def test_foreign_host_is_rejected(host):
    assert client.get("/api/health", headers={"host": host}).status_code == 403


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost.evil.example"])
def test_foreign_origin_is_rejected(origin):
    assert client.post("/api/cli/login/cancel", headers={"origin": origin}).status_code == 403


def test_local_origin_is_allowed():
    assert client.get("/api/health", headers={"origin": "http://localhost:5173"}).status_code == 200
