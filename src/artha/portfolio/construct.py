"""Portfolio construction (plan section 8 v1): rank -> constrained weights.

Long-only, top-N equal weight as the base, then:

- position cap (6% default) and sector cap (25%) via iterative clipping;
  clipped excess is NOT redistributed - it stays in cash, so caps can
  only lower gross, never concentrate it elsewhere;
- ADV participation cap: an order's value may not exceed 2% of the name's
  21-day median traded value, capping how far a weight can MOVE per
  rebalance at a given capital;
- no-trade bands: deltas smaller than 25% of target weight do not trade;
  OR (Track C C3, Garleanu-Pedersen style) ``trade_speed`` partial
  adjustment: w_new = prior + tau * (target - prior), replacing bands;
- volatility targeting: gross exposure scaled by target_vol / realized
  trailing vol, clamped to [0, 1] (no leverage); remainder is cash.

Track C C2 weighting schemes inside the selected top-N: ``equal``
(default), ``ivol`` (inverse trailing vol), ``minvar`` (long-only
minimum variance from a Ledoit-Wolf shrunk covariance). ivol/minvar
fall back to equal weight when risk inputs are missing.

The constructor also emits per-rebalance constraint check results; the P5
gate requires zero violations across the backtest.
"""

from dataclasses import dataclass, field
from typing import Final

import numpy as np

from artha.portfolio.riskmodel import inverse_vol_weights, min_var_weights

TOP_N: Final = 25
POSITION_CAP: Final = 0.06
SECTOR_CAP: Final = 0.25
ADV_PARTICIPATION: Final = 0.02
NO_TRADE_BAND: Final = 0.25
TARGET_VOL: Final = 0.135  # midpoint of the plan's 12-15% band
FULL_EXIT_WEIGHT: Final = 0.005  # partial-adjustment exits liquidate below this
_TOL: Final = 1e-9


def production_constructor(capital: float, sector_map: dict[str, str]) -> "Constructor":
    """THE live configuration. Single source of truth for every script that
    trades or replays the production book (paper day, weekly review,
    readiness) — change here, nowhere else.

    Since 2026-07-19 (Track C gate, docs/research/track-c-study.md):
    Ledoit-Wolf min-var weights + Garleanu-Pedersen tau 0.5 — Sharpe 1.055
    vs 0.960 equal+bands, maxDD -21% vs -27%, turnover 3.8x vs 5.2x."""
    return Constructor(capital=capital, sector_map=sector_map, scheme="minvar", trade_speed=0.5)


@dataclass
class ConstraintReport:
    violations: list[str] = field(default_factory=list)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.violations.append(message)


@dataclass(frozen=True)
class Constructor:
    top_n: int = TOP_N
    position_cap: float = POSITION_CAP
    sector_cap: float = SECTOR_CAP
    adv_participation: float = ADV_PARTICIPATION
    no_trade_band: float = NO_TRADE_BAND
    target_vol: float = TARGET_VOL
    capital: float = 0.0
    sector_map: dict[str, str] = field(default_factory=dict)
    scheme: str = "equal"  # equal | ivol | minvar (C2)
    trade_speed: float | None = None  # partial adjustment tau; None = bands (C3)

    def build(
        self,
        ranked: list[tuple[str, float]],  # (symbol, adv_value), best first
        prior_weights: dict[str, float],
        realized_vol: float | None,
        report: ConstraintReport,
        adv_map: dict[str, float] | None = None,
        vols: dict[str, float] | None = None,
        cov: tuple[list[str], "np.ndarray"] | None = None,
    ) -> dict[str, float]:
        picks = ranked[: self.top_n]
        if not picks:
            return dict(prior_weights)
        names = [sym for sym, _ in picks]
        weights = self._base_weights(names, vols, cov)
        weights = self._apply_position_cap(weights)
        weights = self._apply_sector_cap(weights)

        # vol targeting scales gross before banding/participation
        if realized_vol is not None and realized_vol > 0:
            gross = min(1.0, self.target_vol / realized_vol)
            weights = {s: w * gross for s, w in weights.items()}

        # trading rule vs prior (drifted) weights: no-trade bands, or
        # Garleanu-Pedersen partial adjustment when trade_speed is set
        banded: dict[str, float] = {}
        for sym in set(weights) | set(prior_weights):
            target = weights.get(sym, 0.0)
            prior = prior_weights.get(sym, 0.0)
            if self.trade_speed is not None:
                if target <= _TOL and prior < FULL_EXIT_WEIGHT:
                    banded[sym] = 0.0  # full exit: no geometric zombie tail
                else:
                    banded[sym] = prior + self.trade_speed * (target - prior)
            elif target > 0 and abs(target - prior) < self.no_trade_band * target:
                banded[sym] = prior  # hold
            else:
                banded[sym] = target
        banded = {s: w for s, w in banded.items() if w > _TOL}

        # ADV participation cap limits the move per name. A missing ADV must
        # fail OPEN: capping an exit at zero would freeze departing names in
        # the book forever (found the hard way - it silently pinned gross at
        # 1.0 and erased vol targeting).
        adv = {**(adv_map or {}), **dict(picks)}
        if self.capital > 0:
            capped: dict[str, float] = {}
            for sym in set(banded) | set(prior_weights):
                target = banded.get(sym, 0.0)
                prior = prior_weights.get(sym, 0.0)
                adv_value = adv.get(sym)
                if adv_value is not None:
                    max_move = self.adv_participation * adv_value / self.capital
                    delta = target - prior
                    if abs(delta) > max_move:
                        target = prior + max_move * (1 if delta > 0 else -1)
                if target > _TOL:
                    capped[sym] = target
            banded = capped

        total = sum(banded.values())
        if total > 1.0 + _TOL:  # participation caps cannot push gross over 1
            banded = {s: w / total for s, w in banded.items()}

        self._verify(banded, report)
        return banded

    def _base_weights(
        self,
        names: list[str],
        vols: dict[str, float] | None,
        cov: tuple[list[str], "np.ndarray"] | None,
    ) -> dict[str, float]:
        if self.scheme == "ivol" and vols:
            return inverse_vol_weights(names, vols)
        if self.scheme == "minvar" and cov is not None:
            cov_names, matrix = cov
            if cov_names == names:
                return min_var_weights(names, matrix)
            # partial risk coverage (short-history names excluded from the
            # covariance): min-var over the covered subset, equal share for
            # the rest — the model degrades name-by-name, never all-or-nothing
            covered = [n for n in cov_names if n in names]
            if covered:
                rest = [n for n in names if n not in covered]
                sub = min_var_weights(covered, matrix)
                frac = len(covered) / len(names)
                out = {n: w * frac for n, w in sub.items()}
                out.update(dict.fromkeys(rest, (1 - frac) / len(rest)) if rest else {})
                return out
        return dict.fromkeys(names, 1.0 / len(names))

    def _apply_position_cap(self, weights: dict[str, float]) -> dict[str, float]:
        """Clip to the position cap and REDISTRIBUTE the clipped excess to
        uncapped names (iteratively), so concentrated risk-model books do
        not silently leak gross into cash."""
        for _ in range(10):
            over = {s: w for s, w in weights.items() if w > self.position_cap + _TOL}
            if not over:
                return weights
            excess = sum(w - self.position_cap for w in over.values())
            weights = {s: min(w, self.position_cap) for s, w in weights.items()}
            under = {s: w for s, w in weights.items() if w < self.position_cap - _TOL}
            room = sum(self.position_cap - w for w in under.values())
            if room <= _TOL:
                return weights  # everyone capped: excess genuinely becomes cash
            scale = min(1.0, excess / room)
            weights = {
                s: (w + (self.position_cap - w) * scale if s in under else w)
                for s, w in weights.items()
            }
        return weights

    def _apply_sector_cap(self, weights: dict[str, float]) -> dict[str, float]:
        for _ in range(10):
            sector_w: dict[str, float] = {}
            for sym, w in weights.items():
                sector_w[self._sector(sym)] = sector_w.get(self._sector(sym), 0.0) + w
            # UNKNOWN is not one industry; capping it as a bucket would
            # punish names merely missing sector data
            over = {
                s: w for s, w in sector_w.items() if s != "UNKNOWN" and w > self.sector_cap + _TOL
            }
            if not over:
                return weights
            for sector, w_sum in over.items():
                scale = self.sector_cap / w_sum
                weights = {
                    sym: (w * scale if self._sector(sym) == sector else w)
                    for sym, w in weights.items()
                }
        return weights

    def _sector(self, symbol: str) -> str:
        return self.sector_map.get(symbol) or "UNKNOWN"

    def _verify(self, weights: dict[str, float], report: ConstraintReport) -> None:
        gross = sum(weights.values())
        report.check(gross <= 1.0 + 1e-6, f"gross {gross:.4f} > 1")
        report.check(all(w >= -_TOL for w in weights.values()), "short position")
        for sym, w in weights.items():
            # bands may hold a slightly over-cap drifted position; allow drift slack
            report.check(
                w <= self.position_cap * (1 + self.no_trade_band) + 1e-6,
                f"{sym} weight {w:.4f} breaches position cap",
            )
        sector_w: dict[str, float] = {}
        for sym, w in weights.items():
            sector_w[self._sector(sym)] = sector_w.get(self._sector(sym), 0.0) + w
        for sector, w_sum in sector_w.items():
            if sector == "UNKNOWN":
                continue
            report.check(
                w_sum <= self.sector_cap * (1 + self.no_trade_band) + 1e-6,
                f"sector {sector} {w_sum:.4f} breaches sector cap",
            )
