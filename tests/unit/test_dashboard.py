"""Dashboard API serves artifacts read-only from ARTHA_DATA_DIR."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from artha.dashboard.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ARTHA_DATA_DIR", str(tmp_path))
    reports = tmp_path / "reports"
    (reports / "paper").mkdir(parents=True)
    (reports / "p5_tearsheet_20260101T000000Z.json").write_text(
        json.dumps({"constructed_momentum": {"sharpe": 0.97}, "dsr": 0.64}), encoding="utf-8"
    )
    (reports / "model_study_20260101T000000Z.json").write_text(
        json.dumps({"ridge": {"mean_ic": 0.043}}), encoding="utf-8"
    )
    (reports / "model_study_20260102T000000Z.json").write_text(
        json.dumps({"cpcv": {"pbo": 0.86}}), encoding="utf-8"
    )
    (reports / "ledger.jsonl").write_text(
        json.dumps({"model": "ridge", "net_sharpe": 0.84}) + "\n", encoding="utf-8"
    )
    (reports / "paper" / "paper_log.jsonl").write_text(
        json.dumps({"trade_date": "2026-07-17", "equity": 2.5e6}) + "\n", encoding="utf-8"
    )
    return TestClient(app)


def test_index_serves_static_page(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<canvas" in r.text


def test_tearsheet_returns_latest(client: TestClient) -> None:
    r = client.get("/api/tearsheet")
    assert r.status_code == 200
    assert r.json()["constructed_momentum"]["sharpe"] == 0.97


def test_model_study_merges_batches(client: TestClient) -> None:
    body = client.get("/api/model_study").json()
    assert body["ridge"]["mean_ic"] == 0.043
    assert body["cpcv"]["pbo"] == 0.86


def test_jsonl_endpoints(client: TestClient) -> None:
    assert client.get("/api/ledger").json()[0]["model"] == "ridge"
    assert client.get("/api/paper_log").json()[0]["trade_date"] == "2026-07-17"


def test_missing_report_is_404(client: TestClient) -> None:
    assert client.get("/api/event_alpha").status_code == 404
    assert client.get("/api/benchmark").status_code == 404
