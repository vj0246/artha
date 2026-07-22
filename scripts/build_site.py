"""Build the public showcase page from the repository's own result files.

Usage:
    uv run --no-sync python scripts/build_site.py

Reads the latest report JSONs plus the construction-v2 daily series,
extracts exactly the metrics the page displays, and injects them into
`site/template.html` to produce `site/index.html` — a single
self-contained file with no external requests.

Static by design: every number on that page is a research result that
changes at most quarterly, so there is nothing to serve dynamically and
no backend to run. Re-run this script after any study, then redeploy.

The page shows research results only — never live positions, equity or
operational state (that is the localhost dashboard, ADR 0012).
"""

import collections
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

from artha.config import load_settings

LIVE_CONFIG = "minvar_tau50"


def _latest(reports: Path, pattern: str) -> dict:
    files = sorted(reports.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no report matching {pattern}")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _metrics(rets: np.ndarray, dates: list, tri: dict) -> dict:
    """Risk, distribution and benchmark-relative stats from the daily net series.

    Everything here is derived from the same `net_return` column the backtest
    reports, so the page can never drift from the study that produced it.
    """
    ann = 252.0
    mu, sd = float(rets.mean()), float(rets.std(ddof=1))
    downside = rets[rets < 0]
    dsd = float(downside.std(ddof=1)) if downside.size > 1 else 0.0

    curve = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(curve)
    dd = curve / peak - 1
    max_dd = float(dd.min())
    cagr = float(curve[-1] ** (ann / len(rets)) - 1)

    # longest stretch below a prior peak, in trading days
    under, longest = 0, 0
    for x in dd:
        under = under + 1 if x < -1e-12 else 0
        longest = max(longest, under)

    # benchmark daily returns aligned to the same dates
    bser = [tri.get(d) for d in dates]
    pairs = [
        (r, bser[i] / bser[i - 1] - 1)
        for i, r in enumerate(rets)
        if i and bser[i] is not None and bser[i - 1] is not None
    ]
    sr = np.array([p[0] for p in pairs])
    br = np.array([p[1] for p in pairs])
    cov = float(np.cov(sr, br)[0, 1])
    bvar = float(br.var(ddof=1))
    beta = cov / bvar if bvar else 0.0
    active = sr - br
    te = float(active.std(ddof=1))

    # monthly buckets for win rate / best / worst
    monthly: dict = collections.defaultdict(float)
    for d, r in zip(dates, rets, strict=True):
        monthly[(d.year, d.month)] = (1 + monthly[(d.year, d.month)]) * (1 + float(r)) - 1
    mv = np.array(list(monthly.values()))

    up, dn = br > 0, br < 0

    def pct(x: float) -> float:
        return round(x * 100, 1)

    return {
        "cagr": pct(cagr),
        "vol": pct(sd * np.sqrt(ann)),
        "sharpe": round(mu / sd * np.sqrt(ann), 2) if sd else 0.0,
        "sortino": round(mu / dsd * np.sqrt(ann), 2) if dsd else 0.0,
        "calmar": round(cagr / abs(max_dd), 2) if max_dd else 0.0,
        "max_dd": pct(max_dd),
        "underwater_days": longest,
        "beta": round(beta, 2),
        "alpha": pct(float(sr.mean() - beta * br.mean()) * ann),
        "tracking_error": pct(te * np.sqrt(ann)),
        "info_ratio": round(float(active.mean()) / te * np.sqrt(ann), 2) if te else 0.0,
        "correlation": round(float(np.corrcoef(sr, br)[0, 1]), 2),
        "up_capture": round(float(sr[up].mean() / br[up].mean()), 2) if up.any() else 0.0,
        "down_capture": round(float(sr[dn].mean() / br[dn].mean()), 2) if dn.any() else 0.0,
        "monthly_win_rate": pct(float((mv > 0).mean())),
        "best_month": pct(float(mv.max())),
        "worst_month": pct(float(mv.min())),
        "daily_skew": round(float(((rets - mu) ** 3).mean() / sd**3), 2) if sd else 0.0,
        "var95": pct(float(np.percentile(rets, 5))),
        "cvar95": pct(float(rets[rets <= np.percentile(rets, 5)].mean())),
        "n_days": len(rets),
        "n_months": len(mv),
    }


def collect() -> dict:
    settings = load_settings()
    reports, curated = settings.reports_dir, settings.curated_dir
    out: dict = {}

    daily = pl.read_parquet(reports / "construction_v2_daily.parquet")
    live = daily.filter(pl.col("config") == LIVE_CONFIG).sort("trade_date")
    equity = (1 + live["net_return"]).cum_prod().to_numpy()
    dates = live["trade_date"].to_list()
    bench = pl.read_parquet(curated / "benchmarks" / "nifty500.parquet").sort("trade_date")
    tri = {r["trade_date"]: r["tr_index"] for r in bench.iter_rows(named=True)}

    # month-end sample keeps the payload small without distorting the shape
    series, base = [], None
    for i, (d, e) in enumerate(zip(dates, equity, strict=True)):
        last = i == len(dates) - 1
        if i and (d.year, d.month) == (dates[i - 1].year, dates[i - 1].month) and not last:
            continue
        b = tri.get(d)
        if b is None:
            continue
        base = base or b
        series.append([d.isoformat(), round(float(e) * 100, 2), round(float(b / base) * 100, 2)])
    out["equity"] = series

    def drawdown(values: list[float]) -> list[float]:
        peak, path = -1e9, []
        for v in values:
            peak = max(peak, v)
            path.append(round((v / peak - 1) * 100, 2))
        return path

    out["dd_strategy"] = drawdown([r[1] for r in series])
    out["dd_bench"] = drawdown([r[2] for r in series])

    rets = live["net_return"].to_numpy()
    rolling = []
    for i in range(251, len(rets), 21):
        window = rets[i - 251 : i + 1]
        sd = window.std(ddof=1)
        rolling.append(
            [
                dates[i].isoformat(),
                round(float(window.mean() / sd * np.sqrt(252)), 3) if sd else 0.0,
            ]
        )
    out["rolling_sharpe"] = rolling

    out["metrics"] = _metrics(rets, dates, tri)

    sizing = _latest(reports, "live_readiness_*.json")["sizing"]["levels"]
    out["sizing"] = [
        [
            k,
            round(v["net_sharpe"], 3),
            round(v["dp_charge_bps_per_sell"], 1),
            round(v["weight_granularity_at_median_price"] * 100, 1),
        ]
        for k, v in sizing.items()
    ]

    construction = _latest(reports, "construction_v2_2026*.json")
    out["construction"] = [
        [
            k,
            round(v["sharpe"], 3),
            round(v["cagr"] * 100, 1),
            round(v["max_drawdown"] * 100, 1),
            round(v["turnover_oneway_ann"], 1),
        ]
        for k, v in construction.items()
        if isinstance(v, dict)
    ]

    zoo = _latest(reports, "d3_models_*.json")["expanding"]
    out["zoo"] = [[k, round(v.get("net_sharpe", 0.0), 3)] for k, v in zoo.items()]

    ledger_rows = [
        json.loads(line)
        for line in (reports / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    per_day = collections.Counter(r["run_at"][:10] for r in ledger_rows if r.get("run_at"))
    running, growth = 0, []
    for day, n in sorted(per_day.items()):
        running += n
        growth.append([day, running])
    out["ledger_growth"] = growth
    out["n_trials"] = len(ledger_rows)
    return out


def main() -> int:
    site = Path(__file__).resolve().parent.parent / "site"
    template = (site / "template.html").read_text(encoding="utf-8")
    data = collect()
    payload = json.dumps(data, separators=(",", ":"))
    (site / "index.html").write_text(template.replace("__DATA__", payload), encoding="utf-8")
    size = (site / "index.html").stat().st_size
    print(f"site/index.html written: {size:,} bytes")
    print(
        f"  {len(data['equity'])} monthly points · {len(data['rolling_sharpe'])} rolling windows "
        f"· {data['n_trials']} ledger trials"
    )
    print(f"  final index: strategy {data['equity'][-1][1]} vs benchmark {data['equity'][-1][2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
