"""Integration tests for the FastAPI surface (offline / deterministic)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.evidence_fabric.store import _store
from src.stepup_verification.persistence import clear_confirmed


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
    monkeypatch.setenv("SKIP_AMD_CHECK", "true")
    from src.orchestration.api import app

    with TestClient(app) as c:
        yield c


class TestApi:
    def test_health(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}

    def test_turn_returns_band_and_posture(self, client: TestClient) -> None:
        _store.clear("api-1")
        clear_confirmed("api-1")
        r = client.post(
            "/v1/turn",
            json={"session_id": "api-1", "turn_text": "my mom said do homework", "turn_number": 1},
        )
        body = r.json()
        assert r.status_code == 200
        assert "posture" in body and "band" in body and "confidence" in body
        assert body["evidence"]["session_id"] == "api-1"
        _store.clear("api-1")

    def test_chat_completions_openai_shape(self, client: TestClient) -> None:
        _store.clear("api-2")
        clear_confirmed("api-2")
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "ageband",
                "messages": [{"role": "user", "content": "I am in 8th grade"}],
                "user": "api-2",
            },
        )
        assert r.status_code == 200
        content = r.json()["choices"][0]["message"]["content"]
        state = json.loads(content)
        assert set(state) >= {"session_id", "band", "confidence", "posture", "evidence", "trace"}
        assert state["session_id"] == "api-2"
        _store.clear("api-2")

    def test_confirm_then_override(self, client: TestClient) -> None:
        _store.clear("api-3")
        clear_confirmed("api-3")
        client.post(
            "/v1/turn",
            json={"session_id": "api-3", "turn_text": "I am in 8th grade", "turn_number": 1},
        )
        assert client.post(
            "/v1/confirm", json={"session_id": "api-3", "band": "adult"}
        ).json()["ok"] is True
        r = client.post(
            "/v1/turn",
            json={"session_id": "api-3", "turn_text": "hello", "turn_number": 2},
        )
        assert r.json()["band"] == "adult"
        _store.clear("api-3")
        clear_confirmed("api-3")
