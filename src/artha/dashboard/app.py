"""Read-only dashboard API over run artifacts (Track B B5, plan 15 item 5).

Usage:
    uv run uvicorn dashboard.app:app --port 8787

Serves JSON from the reports/curated zones plus one static page. Strictly
read-only and localhost-oriented: no writes, no auth, no external assets.
v1 is FastAPI + a dependency-free static page; the plan's Next.js front
end remains an optional upgrade (tradeoff: this ships with zero node
toolchain).
"""

import json
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from artha.config import load_settings

app = FastAPI(title="artha dashboard", docs_url=None, redoc_url=None)
STATIC = Path(__file__).parent / "static"


def _latest(pattern: str) -> dict[str, Any]:
    settings = load_settings()
    files = sorted(settings.reports_dir.glob(pattern))
    if not files:
        raise HTTPException(404, f"no report matching {pattern}")
    return json.loads(files[-1].read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/tearsheet")
def tearsheet() -> dict[str, Any]:
    return _latest("p5_tearsheet_*.json")


@app.get("/api/model_study")
def model_study() -> dict[str, Any]:
    # P3 runs wrote one file per batch (ridge+lgbm, transformer, cpcv);
    # merge oldest-first so later runs override same-named keys.
    settings = load_settings()
    merged: dict[str, Any] = {}
    for path in sorted(settings.reports_dir.glob("model_study_*.json")):
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    if not merged:
        raise HTTPException(404, "no model study reports")
    return merged


@app.get("/api/event_alpha")
def event_alpha() -> dict[str, Any]:
    return _latest("event_alpha_*.json")


@app.get("/api/survivorship")
def survivorship() -> dict[str, Any]:
    return _latest("survivorship_demo_*.json")


@app.get("/api/readiness")
def readiness() -> dict[str, Any]:
    return _latest("live_readiness_*.json")


@app.get("/api/hedge")
def hedge() -> dict[str, Any]:
    return _latest("hedge_study_*.json")


@app.get("/api/research_agent")
def research_agent() -> dict[str, Any]:
    return _latest("research_agent_*.json")


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Operational health written by run_heartbeat.py (Track G)."""
    settings = load_settings()
    path = settings.reports_dir / "paper" / "health.json"
    if not path.exists():
        return {"healthy": None, "status": "heartbeat has never run"}
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@app.get("/api/alerts")
def alerts() -> list[dict[str, Any]]:
    settings = load_settings()
    path = settings.reports_dir / "paper" / "alerts.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows[-50:]


@app.get("/api/construction")
def construction() -> dict[str, Any]:
    return _latest("construction_v2_*.json")


@app.get("/api/spa")
def spa() -> dict[str, Any]:
    return _latest("spa_*.json")


@app.get("/api/regime")
def regime() -> dict[str, Any]:
    return _latest("regime_study_*.json")


@app.get("/api/ledger")
def ledger() -> list[dict[str, Any]]:
    settings = load_settings()
    path = settings.reports_dir / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@app.get("/api/paper_log")
def paper_log() -> list[dict[str, Any]]:
    settings = load_settings()
    path = settings.reports_dir / "paper" / "paper_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@app.get("/api/benchmark")
def benchmark() -> list[dict[str, Any]]:
    settings = load_settings()
    path = settings.curated_dir / "benchmarks" / "nifty500.parquet"
    if not path.exists():
        raise HTTPException(404, "benchmarks not built")
    frame = (
        pl.scan_parquet(path)
        .select("trade_date", "close", "tr_index")
        .collect()
        .with_columns(pl.col("trade_date").cast(pl.String))
    )
    return frame.to_dicts()
