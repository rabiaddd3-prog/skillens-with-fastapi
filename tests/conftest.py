import pytest


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    """A fixed admin token, so test runs never overwrite runs/admin_token.txt of a running server."""
    import os

    if "SKILLLENS_ADMIN_TOKEN" not in os.environ:
        monkeypatch.setenv("SKILLLENS_ADMIN_TOKEN", "test-admin-token")
