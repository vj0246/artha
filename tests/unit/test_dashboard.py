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
    assert "chart-tri" in r.text  # SVG chart mount point


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


def test_health_and_alerts_degrade_gracefully(client: TestClient, tmp_path: Path) -> None:
    # heartbeat never run: health reports unknown rather than erroring
    assert client.get("/api/health").json()["healthy"] is None
    assert client.get("/api/alerts").json() == []

    paper = tmp_path / "reports" / "paper"
    (paper / "health.json").write_text(
        json.dumps({"healthy": False, "problems": ["cycle not running"], "b1_progress": "3/30"}),
        encoding="utf-8",
    )
    (paper / "alerts.jsonl").write_text(
        json.dumps({"at": "2026-07-20T12:00:00+00:00", "severity": "critical", "message": "frozen"})
        + "\n",
        encoding="utf-8",
    )
    h = client.get("/api/health").json()
    assert h["healthy"] is False
    assert h["problems"] == ["cycle not running"]
    assert client.get("/api/alerts").json()[0]["severity"] == "critical"


def test_missing_report_is_404(client: TestClient) -> None:
    assert client.get("/api/event_alpha").status_code == 404
    assert client.get("/api/benchmark").status_code == 404
    assert client.get("/api/readiness").status_code == 404
    assert client.get("/api/hedge").status_code == 404
    assert client.get("/api/construction").status_code == 404
    assert client.get("/api/spa").status_code == 404
    assert client.get("/api/regime").status_code == 404


def test_readiness_and_hedge_serve_latest(client: TestClient, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    (reports / "live_readiness_20260101T000000Z.json").write_text(
        json.dumps({"go_live_checklist": {"b1_30_clean_sessions": False}}), encoding="utf-8"
    )
    (reports / "hedge_study_20260101T000000Z.json").write_text(
        json.dumps({"gate_pass": True, "residual_beta": -0.02}), encoding="utf-8"
    )
    assert client.get("/api/readiness").json()["go_live_checklist"] == {
        "b1_30_clean_sessions": False
    }
    assert client.get("/api/hedge").json()["gate_pass"] is True
    (reports / "construction_v2_20260101T000000Z.json").write_text(
        json.dumps({"minvar_tau50": {"sharpe": 1.119}}), encoding="utf-8"
    )
    (reports / "spa_20260101T000000Z.json").write_text(
        json.dumps({"spa_p_value": 0.0445}), encoding="utf-8"
    )
    assert client.get("/api/construction").json()["minvar_tau50"]["sharpe"] == 1.119
    assert client.get("/api/spa").json()["spa_p_value"] == 0.0445
