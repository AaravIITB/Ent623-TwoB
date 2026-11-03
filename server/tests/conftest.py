import os
import sys
import tempfile
from pathlib import Path

os.environ["TAXMIND_DATA"] = tempfile.mkdtemp(prefix="taxmind_test_")
os.environ["TAXMIND_ADMIN_PASSWORD"] = "admin123"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from taxmind_server.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}
