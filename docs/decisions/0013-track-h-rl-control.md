# ADR 0013: adopt Track H — RL as control, plus a self-improving agent

Date: 2026-07-20. At VJ's direction ("add reinforcement learning, and
it should improve on itself"). Full plan: docs/TRACK_H_PLAN.md.

## Decision

Reinforcement learning enters this project as a CONTROL method over the
system's own sequential decisions (trading speed), and as a
self-improvement loop for the research agent (bandit over proposal
families). It does NOT enter as a return predictor or a direct
weight-setter.

## Why the prediction version is refused

Track D evaluated ridge, LGBM, GRU, LSTM, a transformer and their
ensemble against an always-long floor under a leak-proof protocol on
ICICIBANK: none beat the floor net of costs, under expanding OR
rolling retraining. P3 measured PBO 0.86 for cross-sectional ML. The
project's deflated Sharpe is 0.20 against ~98 ledger trials.

An RL return-predictor would add the largest hyperparameter surface in
the toolkit to a problem already measured as having no exploitable
signal at this horizon, while spending credibility the ledger says we
do not have. It would also contradict the project's own working paper,
which criticises exactly this class of self-deception.

## Why the control version is legitimate

The system already makes sequential decisions with fixed constants
(tau = 0.5, gross scalar). Garleanu-Pedersen is the analytical solution
to that control problem; whether a state-dependent policy beats the
constant is well posed and requires no return forecast.

## Algorithm choice, justified by the problem

- **Contextual bandit, not MDP**: at Rs 2-5L we have no market impact,
  so actions do not alter the next state. An MDP formulation would
  model a market influence we do not have.
- **Linear/tabular (LinUCB, Thompson), not deep RL**: ~700 weekly
  decisions exist in the entire history; PPO/DQN need orders of
  magnitude more. Sample size dictates model class.

## Gates

H1's learned policy must beat fixed tau = 0.5 on net Sharpe over a
held-out final third AND the full walk-forward, with PBO < 0.5 —
pre-registered before running. Failing any criterion publishes a null
and ships nothing. H2 never touches production by construction.
