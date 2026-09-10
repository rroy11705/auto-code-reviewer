import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app, verify_github_signature
from app.config import settings

client = TestClient(app)


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "auto-code-reviewer"


def test_webhook_rejects_invalid_signature():
    secret = "test_webhook_secret_123"
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", secret):
        payload = json.dumps({"action": "opened"}).encode("utf-8")
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid_signature_hex",
        }
        response = client.post("/webhook/github", content=payload, headers=headers)
        assert response.status_code == 401
        assert "Invalid HMAC signature" in response.json()["detail"]


def test_webhook_ignores_non_pull_request_event():
    secret = "test_webhook_secret_123"
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", secret):
        payload = json.dumps({"action": "created"}).encode("utf-8")
        sig = compute_signature(payload, secret)
        headers = {
            "X-GitHub-Event": "star",
            "X-Hub-Signature-256": sig,
        }
        response = client.post("/webhook/github", content=payload, headers=headers)
        assert response.status_code == 200
        assert "ignored" in response.json()["message"]


def test_webhook_accepts_valid_pull_request():
    secret = "test_webhook_secret_123"
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", secret):
        payload_dict = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add feature",
                "html_url": "https://github.com/org/repo/pull/42",
            },
            "repository": {
                "full_name": "org/repo",
            },
            "sender": {
                "login": "octocat",
            },
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        sig = compute_signature(payload_bytes, secret)
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": sig,
        }

        with patch("app.services.reviewer.ReviewOrchestrator.process_pull_request_event") as mock_orch:
            response = client.post("/webhook/github", content=payload_bytes, headers=headers)
            assert response.status_code == 202
            assert response.json()["status"] == "accepted"
            assert response.json()["action"] == "opened"
