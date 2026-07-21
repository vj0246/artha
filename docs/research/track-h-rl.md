# Track H: RL as control, and an agent that learns from itself

Date: 2026-07-21. Reports `h1_rl_control_20260721T162640Z.json`,
`research_agent_20260721T162858Z.json`. Plan and rationale: ADR 0013,
docs/TRACK_H_PLAN.md.

Framing, decided before any code (ADR 0013): RL enters this project as
a **control** method over decisions the system already makes, never as
a return predictor — Track D had already shown that the entire model
zoo (ridge/LGBM/GRU/LSTM/transformer/ensemble) loses to buy-and-hold at
this horizon, and DSR 0.20 leaves no credibility to spend on lottery
tickets. Two properties then fixed the algorithm: at Rs 2-5L we have no
market impact (so actions do not change the next state → contextual
bandit, not MDP), and only ~700 weekly decisions exist in the entire
history (so LinUCB/Thompson, not PPO).

## H1: learned trading speed vs the fixed constant — NULL

At each weekly rebalance a LinUCB agent chose tau ∈ {0.25, 0.50, 0.75}
from a knowable-at-t context (benchmark drawdown, vol-stress flag),
rewarded with the realised net return of the following week. 728
decisions, strictly online walk-forward.

| policy | net Sharpe | CAGR | maxDD |
|---|---|---|---|
| fixed tau 0.25 | 0.996 | 13.2% | −29.7% |
| **fixed tau 0.50 (shipped)** | **1.018** | 13.7% | −28.3% |
| fixed tau 0.75 | 1.017 | 13.7% | −27.4% |
| LinUCB learned policy | 1.022 | 13.7% | −29.3% |

Pre-registered gates: full-sample win **PASS** (1.022 vs 1.018 — a
+0.005 Sharpe difference, i.e. nothing); held-out final third **FAIL**
(1.071 vs 1.079); PBO **FAIL at 0.93**.

**Verdict: HOLD, null published. Nothing ships.**

The three diagnostics agree and are worth stating plainly, because they
explain *why* rather than just reporting failure:

1. **The objective surface is flat.** The three fixed baselines span
   0.996-1.018 Sharpe. There is no meaningful difference between
   trading speeds to discover, so no policy can exploit one.
2. **The agent's own behaviour says so.** Action counts came out
   258/246/224 — near-uniform. LinUCB found no context that predicted
   which tau would win, so it kept exploring rather than converging.
   An agent that refuses to commit is telling you the truth about the
   problem.
3. **PBO 0.93** confirms it: picking the "best" tau in-sample lands in
   the bottom half out-of-sample 93% of the time. That is the signature
   of selecting among indistinguishable options.

The honest reading is not "RL failed" but "**this control problem has
no exploitable state-dependence at this granularity**". Garleanu-
Pedersen's constant is doing its job; the analytical solution is
already close enough to optimal that a learner cannot improve on it
with the information available. That is a satisfying result: theory
holds, and we now have evidence rather than assumption.

## H2: the research agent now learns from its own history — WORKING

The B6 agent proposed the same seeds forever and never learned which
KINDS of idea paid off. It now carries a Thompson-sampling posterior
over proposal families (volatility-structure, liquidity,
range/position, reversal, seasonality), rebuilt from the trial ledger's
own record of realised IC deltas — the system's evidence, not a
separate mutable belief that could drift from what happened.

Demonstrated empirically across two consecutive runs:

- **Run 1** — memory ranked `liquidity` first, so the agent proposed
  its two liquidity ideas ahead of the default seed order. Both came
  back negative (`illiq_trend_5_63` −0.0009, `turnover_shock_5d`
  −0.0006); `vol_structure` returned +0.0001.
- **Run 2** — the posterior updated and the ranking **flipped**:
  `vol_structure` first, `liquidity` demoted to second. The agent
  changed what it tries next because of what it learned.

That is the whole self-improvement loop, and deliberately the *safe*
form of it: the agent compounds knowledge without compounding risk. It
never edits the live book; graduation to the feature library still
requires a full model study by hand; and every screen it runs is still
ledgered, so multiple-testing honesty survives automation. An agent
that "improved itself" by rewriting the production strategy would be an
unbacktested change to real money — explicitly out of scope (ADR 0013).

Note the loop is currently learning that most of its own ideas do not
help — deltas of ±0.001 IC against a 0.042 baseline. That is the
correct thing for it to learn on this evidence, and it will keep
proposing from whichever family is least disconfirmed, monthly, for as
long as the scheduled task runs.

## H3: execution RL — blocked, and honestly probably not worth it

The canonical legitimate RL-in-finance application is order execution
(Nevmyvaka-Feng-Kearns 2006). It needs live fills, blocked on Kite
credentials. Recorded plainly: even unblocked, ~25 orders/week at
Rs 2-5L in top-decile-liquidity names have almost no execution alpha to
capture. Documented as understood, not queued as work.

## What this track adds to the record

A second published null, with a mechanism rather than a shrug — and a
demonstration that the honest version of "add RL" is to ask *where the
decisions actually are*, choose the algorithm from the sample size and
the market-impact structure, and let a pre-registered gate decide. The
five ledger trials it cost are recorded like every other.
