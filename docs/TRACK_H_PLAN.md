# TRACK_H_PLAN v1 (2026-07-20) — sequential decision-making & self-improvement

Adopted at VJ's direction (ADR 0013): "add reinforcement learning, and
it should improve on itself." This plan says exactly where RL belongs
in this system, where it does not, and why — because the wrong version
of this track would actively damage the project.

## The framing decision: RL is a CONTROL tool, not a prediction tool

**Not built, with evidence**: an RL agent that predicts returns or picks
weights directly from prices. Track D already ran ridge, LGBM, GRU,
LSTM, a transformer and their ensemble against a buy-and-hold floor on
a liquid Indian large-cap under a leak-proof protocol; none beat the
floor net of costs, under either retrain window. P3 found PBO 0.86
cross-sectionally. A return-predicting RL agent is that same null with
a much larger hyperparameter surface, and the project's deflated Sharpe
is already 0.20 against ~98 ledger trials — there is almost no
statistical credibility left to spend on lottery tickets. Building it
would contradict our own published paper on people fooling themselves.

**Built, because it is genuinely a control problem**: the system
currently makes sequential decisions with FIXED constants — trading
speed (tau = 0.5) and gross exposure. Garleanu-Pedersen is the
analytical solution to exactly this control problem under quadratic
costs; we shipped its constant approximation. Whether a state-dependent
policy beats the constant is an open, well-posed, testable question
that does not require predicting returns.

## The algorithm follows from the problem, not from fashion

Two properties decide it:

1. **No market impact.** At Rs 2-5L our orders are invisible to the
   market, so our actions do not change the next state. The problem is
   therefore a CONTEXTUAL BANDIT, not a Markov decision process.
   Modelling it as an MDP would be pretending our trades move the
   world.
2. **~700 weekly decisions in the entire history.** Deep RL (PPO, DQN)
   needs 10^5-10^6 interactions. With 700, the honest choice is a
   linear/tabular learner: LinUCB or Thompson sampling. Choosing model
   complexity from sample size is the difference between doing RL and
   cosplaying it.

Sources: Sutton & Barto ch. 2 (bandits) and ch. 6; Li et al. (2010)
"A Contextual-Bandit Approach to Personalized News Article
Recommendation" (LinUCB); Moody & Saffell (1998) "Performance Functions
and Reinforcement Learning for Trading Systems" (differential Sharpe as
a reward); Nevmyvaka, Feng & Kearns (2006) for the canonical legitimate
RL-in-finance application (execution, which we cannot use yet — see
H3).

## H1: contextual bandit control of trading speed

**What.** At each weekly rebalance, choose tau from {0.25, 0.50, 0.75}
given an observable, knowable-at-t context (benchmark drawdown state,
trailing benchmark vol percentile, book turnover pressure, dispersion
of the signal). Reward = the realised net return over the following
week, i.e. the money the decision actually made after costs.

**Honesty mechanics.** Rewards for all three actions are precomputed
by running the standard backtest once per fixed tau and recording each
rebalance's forward net return — legitimate precisely BECAUSE there is
no market impact, so the counterfactual is well defined. The agent then
learns strictly online, walk-forward: at rebalance t it may use only
outcomes from rebalances < t. A no-lookahead unit test asserts that
perturbing future rewards cannot change past actions.

**Gate (pre-registered, before any run).** The learned policy must beat
fixed tau = 0.5 on net Sharpe over a held-out final third AND across
the full walk-forward, with PBO < 0.5 over the action set. Miss any and
the null is published and nothing ships. Expectation stated up front:
the constant is a strong baseline and the prior is that it survives.

## H2: the self-improving research agent (the "learns from itself" part)

**What.** The B6 research agent proposes candidate features, screens
them, and appends every screen to the trial ledger — but it has no
memory: it proposes the same seeds forever and never learns which
KINDS of ideas paid off. H2 gives it a Thompson-sampling bandit over
proposal FAMILIES (volatility-structure, liquidity, range/position,
reversal, seasonality), whose posterior is rebuilt from the ledger's
own history of realised IC deltas.

Each monthly scheduled run therefore proposes more from families that
have historically improved on the library baseline and fewer from
families that have not — a genuine feedback loop where the system
improves from its own past results, with zero production risk (the
agent never touches the live book; graduation to the feature library
still requires a full model study by hand).

**Why this is the right "self-improvement".** It compounds knowledge
without compounding risk, and every proposal it screens is still
ledgered, so the multiple-testing accounting stays honest as the loop
runs. An agent that self-improved by editing the live strategy would be
an unbacktested change to real money; that is explicitly out of scope.

## H3: execution RL — BLOCKED, and probably never worth it

The canonical legitimate RL application in finance is order execution
(Nevmyvaka-Feng-Kearns). It needs live fills, which are blocked on Kite
credentials. Recorded honestly: even unblocked, our ~25 orders/week at
Rs 2-5L in top-decile-liquidity names have essentially no execution
alpha to capture. It is documented as understood, not queued.

## Constraints inherited (non-negotiable)

- Every configuration appends to the trial ledger BEFORE its result is
  read; DSR is refreshed against the new count.
- Nothing ships to `production_constructor()` without the full battery
  (CPCV/PBO, SPA, DSR) and a deliberate B1 clock restart — the same bar
  that held the C7 blend at HOLD.
- No new dependencies: numpy only.

## Status 2026-07-21: TRACK H EXECUTED (docs/research/track-h-rl.md)

**H1 NULL PUBLISHED.** LinUCB over tau ∈ {0.25, 0.50, 0.75}, 728
weekly decisions, online walk-forward: learned 1.022 vs fixed-0.50
1.018 Sharpe (full sample, i.e. no difference), LOSES the held-out
final third (1.071 vs 1.079), PBO 0.93. Action counts near-uniform
(258/246/224) — the agent found no exploitable context and kept
exploring. Diagnosis, not a shrug: the objective surface is flat (the
three fixed baselines span 0.996-1.018), so Garleanu-Pedersen's
constant is already close enough to optimal that a learner cannot beat
it with available information. Nothing ships.

**H2 WORKING.** The research agent now carries a Thompson posterior
over proposal families, rebuilt from the ledger's own screen history.
Demonstrated across two runs: run 1 ranked `liquidity` first and both
its liquidity ideas scored negative; run 2 flipped the ranking to
`vol_structure`. The agent changes what it tries next because of what
it learned — knowledge compounding without risk compounding, since it
never touches the live book and every screen stays ledgered.

**H3** remains blocked on credentials and is recorded as understood
rather than queued.
