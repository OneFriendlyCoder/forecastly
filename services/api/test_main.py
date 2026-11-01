"""Run with: python3 services/api/test_main.py. Needs no database."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app


def check_bad_limits_are_rejected_before_any_query(client):
    for path in ("/deals/at-risk", "/deals/d1/scores", "/deals/d1/events"):
        for limit in ("0", "-1", "1001", "abc", "1.5"):
            response = client.get(f"{path}?limit={limit}")
            assert response.status_code == 400, f"{path} limit={limit}: got {response.status_code}"
            assert "error" in response.json()


def check_only_get_is_allowed(client):
    assert client.post("/deals/at-risk").status_code == 405


if __name__ == "__main__":
    client = TestClient(app)  # lifespan doesn't run, so the pool stays closed
    check_bad_limits_are_rejected_before_any_query(client)
    check_only_get_is_allowed(client)
    print("all api checks passed")
