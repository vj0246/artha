"""B3 go-live readiness evaluation: rigorous, small-sample honest.

Usage:
    uv run --no-sync python scripts/run_live_readiness.py [--capitals 100000 200000 500000]

Six sections, each mapped to a way real deployments actually fail:

1. OPERATIONS   - session discipline: consecutive non-dry sessions vs the
                  NSE calendar, reconcile breaks, freezes, missed days.
                  Ops failures kill more retail systems than alpha decay.
2. TRACKING     - live path vs the research path replayed over the same
                  dates: daily return differences, annualized tracking
                  error, correlation. Divergence means the thing trading
                  is not the thing that was validated.
3. EXECUTION    - realized vs modeled slippage per fill (orders_log),
                  realized turnover vs research expectation. Costs are
                  the only performance component fully under our control.
4. RISK         - realized vol vs the 13.5% target band, drawdown vs the
                  enforced -10%/-15% rails, daily VaR(95) exceptions with
                  a Kupiec proportion-of-failures test.
5. STATISTICS   - live Sharpe with Probabilistic Sharpe Ratio against 0
                  AND against the research Sharpe, plus Minimum Track
                  Record Length: how many sessions before the live
                  evidence can clear 95% confidence. Prevents both panic
                  and euphoria on tiny samples.
6. SIZING       - the question that decides funding: at Rs 1-2L, flat DP
                  charges (Rs 15.34/scrip/day on sells) and integer-share
                  granularity are NOT negligible. Full-cost backtests at
                  each candidate capital give the realistic net Sharpe /
                  CAGR curve and a minimum-viable-capital verdict.

Writes reports/live_readiness_<ts>.json and prints a gate checklist.
Sections degrade to "insufficient data" honestly instead of fabricating
significance from a handful of sessions.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Any, cast

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import DP_CHARGE_RS, nse_spec
from artha.portfolio.construct import Constructor
from artha.risk.live_eval import (
    kupiec_pof,
    min_track_record_length,
    probabilistic_sharpe,
    sharpe_daily,
)

TARGET_VOL = 0.135
VOL_BAND = (0.10, 0.17)  # P5 acceptance band around the target
RESEARCH_SHARPE_ANN = 0.97  # P5 constructed momentum, 2012-2026
MIN_SESSIONS_FOR_STATS = 21
SLIPPAGE_GATE_RATIO = 2.0
TRACKING_TOL_ANN = 0.02  # 2% ann. tracking error vs research replay
DP_DRAG_VIABLE_BPS = 30.0  # ann. DP drag above this = capital too small


def _live_rows(log_path: Any) -> list[dict[str, Any]]:
    from pathlib import Path

    p = Path(str(log_path))
    if not p.exists():
        return []
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if not r.get("dry_run")]


def section_operations(rows: list[dict[str, Any]], sessions: list[date]) -> dict[str, Any]:
    if not rows:
        return {"status": "no live sessions yet"}
    logged = [date.fromisoformat(r["trade_date"]) for r in rows]
    first = logged[0]
    expected = [s for s in sessions if s >= first]
    missed = sorted(set(expected) - set(logged))
    return {
        "first_live_session": str(first),
        "sessions_logged": len(logged),
        "sessions_expected_since_start": len(expected),
        "missed_sessions": [str(d) for d in missed],
        "reconcile_breaks": sum(not r.get("reconcile_ok", True) for r in rows),
        "pretrade_rejects": sum(r.get("orders_rejected", 0) for r in rows),
        "derisk_days": sum(r.get("gross_scalar", 1.0) < 1.0 for r in rows),
        "b1_gate_progress": f"{len(logged)}/30 consecutive clean sessions",
    }


def _live_returns(rows: list[dict[str, Any]]) -> list[float]:
    eq = [r["equity"] for r in rows]
    return [e1 / e0 - 1 for e0, e1 in pairwise(eq) if e0 > 0]


def section_tracking(rows: list[dict[str, Any]], research_daily: pl.DataFrame) -> dict[str, Any]:
    if len(rows) < 5:
        return {"status": f"insufficient data ({len(rows)} sessions; need 5+)"}
    live = pl.DataFrame(
        {
            "trade_date": [date.fromisoformat(r["trade_date"]) for r in rows[1:]],
            "live_return": _live_returns(rows),
        }
    )
    j = live.join(
        research_daily.select("trade_date", pl.col("net_return").alias("research_return")),
        on="trade_date",
        how="inner",
    )
    if j.height < 5:
        return {"status": "insufficient overlapping days with research replay"}
    diff = (j["live_return"] - j["research_return"]).to_list()
    te_ann = (sum(d * d for d in diff) / max(1, len(diff) - 1)) ** 0.5 * 252**0.5
    corr = float(
        pl.Series(j["live_return"])
        .to_frame()
        .with_columns(pl.Series("r", j["research_return"]))
        .select(pl.corr("live_return", "r"))[0, 0]
        or 0.0
    )
    return {
        "overlap_days": j.height,
        "tracking_error_ann": te_ann,
        "correlation": corr,
        "mean_daily_gap_bps": sum(diff) / len(diff) * 10_000,
        "within_tolerance": te_ann <= TRACKING_TOL_ANN,
        "tolerance_ann": TRACKING_TOL_ANN,
    }


def section_execution(settings: Any, research_stats: dict[str, float]) -> dict[str, Any]:
    log = settings.reports_dir / "paper" / "orders_log.jsonl"
    if not log.exists():
        return {"status": "no orders logged yet"}
    rows = {
        r["broker_order_id"]: r
        for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
        if r.get("status") == "FILLED" and r.get("fill_price") and r.get("ref_close")
    }
    live = [r for r in rows.values() if r.get("quote_source") == "kite_ltp"]
    scored = live or list(rows.values())
    slip = [
        (1.0 if r["side"] == "BUY" else -1.0) * (r["fill_price"] / r["ref_close"] - 1) * 10_000
        for r in scored
    ]
    mean_slip = sum(slip) / len(slip) if slip else 0.0
    return {
        "fills": len(rows),
        "fills_live_quoted": len(live),
        "mean_realized_slippage_bps": mean_slip,
        "slippage_degenerate": not live,
        "research_turnover_oneway_ann": research_stats.get("turnover_oneway_ann"),
        "note": "slippage gate activates with kite_ltp quotes (B2)",
    }


def section_risk(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rets = _live_returns(rows)
    if len(rets) < MIN_SESSIONS_FOR_STATS:
        return {
            "status": f"insufficient data ({len(rets)} return obs; need {MIN_SESSIONS_FOR_STATS}+)"
        }
    n = len(rets)
    mean = sum(rets) / n
    vol_ann = (sum((x - mean) ** 2 for x in rets) / (n - 1)) ** 0.5 * 252**0.5
    eq = [r["equity"] for r in rows]
    peak = eq[0]
    max_dd = 0.0
    for e in eq:
        peak = max(peak, e)
        max_dd = min(max_dd, e / peak - 1)
    # parametric daily VaR at the TARGET vol (the model being tested is
    # the sizing model, not the realized sample's own quantile)
    var95_daily = 1.645 * TARGET_VOL / 252**0.5
    exceptions = sum(x < -var95_daily for x in rets)
    return {
        "realized_vol_ann": vol_ann,
        "vol_band": VOL_BAND,
        "vol_in_band": VOL_BAND[0] <= vol_ann <= VOL_BAND[1],
        "max_drawdown_live": max_dd,
        "derisk_rail": -0.10,
        "freeze_rail": -0.15,
        "var95_daily_model": var95_daily,
        "kupiec": kupiec_pof(n, exceptions, 0.95),
    }


def section_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rets = _live_returns(rows)
    out: dict[str, Any] = {"return_obs": len(rets)}
    if len(rets) < 5:
        out["status"] = "insufficient data; MinTRL shown once 5+ observations exist"
        return out
    sr_d = sharpe_daily(rets)
    research_sr_d = RESEARCH_SHARPE_ANN / 252**0.5
    mtrl_vs_zero = min_track_record_length(rets, benchmark_sr=0.0)
    out.update(
        {
            "live_sharpe_ann": sr_d * 252**0.5,
            "psr_vs_zero": probabilistic_sharpe(rets, benchmark_sr=0.0),
            "psr_vs_research": probabilistic_sharpe(rets, benchmark_sr=research_sr_d),
            "research_sharpe_ann": RESEARCH_SHARPE_ANN,
            "min_track_record_days_vs_zero": mtrl_vs_zero,
            "reading": (
                "PSR vs zero > 0.95 means the live record alone proves positive "
                "skill; until MinTRL sessions exist, decisions must lean on the "
                "research evidence, and live data can only VETO (via ops/risk "
                "rails), not confirm"
            ),
        }
    )
    return out


def section_sizing(settings: Any, capitals: list[float]) -> dict[str, Any]:
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    start = date(2019, 1, 1)  # recent-regime window for sizing realism
    px = universe.filter(pl.col("trade_date") >= start)
    cal = TradingCalendar.from_frame(px)
    master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
    sector_map = {
        r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
    }
    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= start)

    latest = px.filter(pl.col("trade_date") == cal.last)
    med_price = cast(float, latest["adj_close"].median())

    out: dict[str, Any] = {"window_start": str(start), "levels": {}}
    for capital in capitals:
        constructor = Constructor(capital=capital, sector_map=sector_map)
        spec = nse_spec(cal, dp_order_value=capital / constructor.top_n)
        res = run_backtest(px, signal, spec, capital=capital, constructor=constructor)
        stats = summarize(res.daily)
        per_name = capital / constructor.top_n
        # flat DP charge as bps of a typical sell + integer-share coarseness
        dp_bps_per_sell = DP_CHARGE_RS / per_name * 10_000
        granularity = med_price / per_name  # weight step per share at median price
        out["levels"][f"{capital:,.0f}"] = {
            "net_sharpe": stats["sharpe"],
            "net_cagr": stats["cagr"],
            "vol": stats["vol"],
            "max_drawdown": stats["max_drawdown"],
            "per_name_notional": per_name,
            "dp_charge_bps_per_sell": dp_bps_per_sell,
            "weight_granularity_at_median_price": granularity,
        }
    levels = out["levels"]
    viable = [
        c
        for c, v in levels.items()
        if v["dp_charge_bps_per_sell"] <= DP_DRAG_VIABLE_BPS and v["net_sharpe"] > 0.5
    ]
    out["min_viable_capital"] = viable[0] if viable else "none of the tested levels"
    out["reading"] = (
        "flat DP charges and integer shares are the small-capital killers: "
        f"a sell costs Rs {DP_CHARGE_RS} per scrip regardless of size, and at "
        "the median book price each share is a large weight step. Fund at or "
        "above min_viable_capital or accept the measured Sharpe haircut."
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capitals",
        type=float,
        nargs="*",
        default=[100_000, 200_000, 500_000, 2_500_000],
    )
    args = parser.parse_args()
    settings = load_settings()

    rows = _live_rows(settings.reports_dir / "paper" / "paper_log.jsonl")

    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    sessions = sorted(universe["trade_date"].unique().to_list())

    # research replay over the live window (for tracking + turnover)
    research_daily = pl.DataFrame(
        {"trade_date": [], "net_return": []},
        schema={"trade_date": pl.Date, "net_return": pl.Float64},
    )
    research_stats: dict[str, float] = {}
    if rows:
        first = date.fromisoformat(rows[0]["trade_date"])
        lookback_start = date(first.year - 2, first.month, 1)  # signal warmup
        px = universe.filter(pl.col("trade_date") >= lookback_start)
        master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
        sector_map = {
            r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
        }
        capital = rows[0]["equity"]
        constructor = Constructor(capital=capital, sector_map=sector_map)
        spec = nse_spec(TradingCalendar.from_frame(px), dp_order_value=capital / 25)
        signal = momentum_12_1(panel).filter(pl.col("trade_date") >= lookback_start)
        res = run_backtest(px, signal, spec, capital=capital, constructor=constructor)
        research_daily = res.daily.filter(pl.col("trade_date") >= first)
        research_stats = summarize(res.daily)

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "operations": section_operations(rows, sessions),
        "tracking": section_tracking(rows, research_daily),
        "execution": section_execution(settings, research_stats),
        "risk": section_risk(rows),
        "statistics": section_statistics(rows),
        "sizing": section_sizing(settings, list(args.capitals)),
    }

    ops = report["operations"]
    stats_sec = report["statistics"]
    checklist = {
        "b1_30_clean_sessions": ops.get("sessions_logged", 0) >= 30
        and ops.get("reconcile_breaks", 1) == 0
        and not ops.get("missed_sessions"),
        "b2_credentials_and_reconcile_week": False,  # flips with reconcile_readonly.jsonl
        "tracking_within_tolerance": bool(report["tracking"].get("within_tolerance", False)),
        "slippage_measurable": not report["execution"].get("slippage_degenerate", True),
        "vol_in_band": bool(report["risk"].get("vol_in_band", False)),
        "live_stats_conclusive": stats_sec.get("psr_vs_zero", 0.0) >= 0.95,
    }
    recon = settings.reports_dir / "paper" / "reconcile_readonly.jsonl"
    if recon.exists():
        rrows = [json.loads(x) for x in recon.read_text(encoding="utf-8").splitlines() if x.strip()]
        ok_days = {r["run_at"][:10] for r in rrows if r.get("ok")}
        checklist["b2_credentials_and_reconcile_week"] = len(ok_days) >= 5
    report["go_live_checklist"] = checklist
    report["verdict"] = (
        "GO candidates only when every checklist item is true; today the "
        "binding constraints are the wall-clock gates, not the code"
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = settings.reports_dir / f"live_readiness_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
